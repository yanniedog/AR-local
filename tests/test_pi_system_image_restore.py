"""Real lossless frame reconstruction; only new local regular files are written."""
import hashlib
import json

import pytest
import zstandard

import pi_system_image_restore as restore


def fixture_set(tmp_path):
    mirror = tmp_path / "downloaded"
    mirror.mkdir()
    contents = [bytes(range(256)) * 100, b"ordinary filesystem bytes\xff\r\n\x1a" * 200]
    parts, offset = [], 0
    for number, content in enumerate(contents, 1):
        compressed = zstandard.ZstdCompressor(level=15).compress(content)
        path = mirror / f"recovery.img.part{number:06d}.zst"
        path.write_bytes(compressed)
        parts.append({"path": path.name, "offset": offset, "length": len(content), "bytes": len(compressed),
                      "sha256": restore.digest(path), "image_bytes_sha256": hashlib.sha256(content).hexdigest()})
        offset += len(content)
    receipt = {"schema": "ar-local-system-recovery-set-v1", "result": "IMAGE_AND_FILESYSTEM_VERIFIED",
               "compression": "zstd-lossless-no-encryption", "compressed_parts": parts, "image_bytes": offset,
               "image_sha256": hashlib.sha256(b"".join(contents)).hexdigest(), "raw_restore_required": True}
    path = mirror / "recovery-set.json"
    path.write_text(json.dumps(receipt))
    return mirror, path, receipt, b"".join(contents)


def test_real_zstd_frames_reassemble_exact_ordinary_image_and_keep_raw_requirement(tmp_path):
    mirror, receipt, _, expected = fixture_set(tmp_path)
    work = tmp_path / "new-private-output"
    result = restore.reassemble(mirror, receipt, restore.digest(receipt), work)
    assert (work / "recovery.img").read_bytes() == expected
    assert result["result"] == "REGULAR_IMAGE_REASSEMBLED_VERIFIED"
    assert result["raw_restore_required"] is True and result["boot_test"] == "NOT_TESTED"
    assert json.loads((work / "image-restore-result.json").read_text())["image_sha256"] == result["image_sha256"]
    with pytest.raises(ValueError, match="new canonical"):
        restore.reassemble(mirror, receipt, restore.digest(receipt), work)


@pytest.mark.parametrize("change", ["compressed", "digest", "order", "traversal", "global", "expansion"])
def test_changed_or_misordered_recovery_bytes_never_get_acceptance(tmp_path, change):
    mirror, receipt_path, receipt, _ = fixture_set(tmp_path)
    if change == "compressed":
        (mirror / receipt["compressed_parts"][0]["path"]).write_bytes(b"changed")
    if change == "order":
        receipt["compressed_parts"].reverse()
    if change == "traversal":
        receipt["compressed_parts"][0]["path"] = "../disk"
    if change == "global":
        receipt["image_sha256"] = "0" * 64
    if change == "expansion":
        receipt["compressed_parts"] = receipt["compressed_parts"][:1]
        receipt["compressed_parts"][0]["length"] = 1
        receipt["image_bytes"] = 1
    receipt_path.write_text(json.dumps(receipt))
    work = tmp_path / "new-private-output"
    digest = "0" * 64 if change == "digest" else restore.digest(receipt_path)
    with pytest.raises(ValueError):
        restore.reassemble(mirror, receipt_path, digest, work)
    assert not (work / "image-restore-result.json").exists()


def test_sparse_windows_or_posix_regular_image_reconstructs_zero_capacity_by_hash(tmp_path):
    from pi_system_sparse import allocation_bound
    mirror = tmp_path / "sparse-mirror"
    mirror.mkdir()
    content = b"\0" * (8 * 1024 ** 2) + bytes(range(256)) * 256 + b"\0" * (8 * 1024 ** 2)
    frame = mirror / "recovery.img.part000001.zst"
    frame.write_bytes(zstandard.ZstdCompressor(level=15).compress(content))
    bound = sum(allocation_bound(content[start:start + 1024 ** 2]) for start in range(0, len(content), 1024 ** 2))
    part = {"path": frame.name, "offset": 0, "length": len(content), "bytes": frame.stat().st_size,
            "sha256": restore.digest(frame), "image_bytes_sha256": hashlib.sha256(content).hexdigest(), "reassembled_allocation_bound": bound}
    body = {"schema": "ar-local-system-recovery-set-v1", "result": "IMAGE_AND_FILESYSTEM_VERIFIED", "compression": "zstd-lossless-no-encryption",
            "compressed_parts": [part], "image_bytes": len(content), "image_sha256": part["image_bytes_sha256"], "raw_restore_required": True,
            "reassembled_allocation_bound": bound}
    receipt = mirror / "recovery-set.json"
    receipt.write_text(json.dumps(body))
    result = restore.reassemble(mirror, receipt, restore.digest(receipt), tmp_path / "new-sparse")
    assert result["image_sha256"] == hashlib.sha256(content).hexdigest()
    assert (tmp_path / "new-sparse/recovery.img").read_bytes() == content
    body["reassembled_allocation_bound"] = 0
    receipt.write_text(json.dumps(body))
    with pytest.raises(ValueError, match="allocation"):
        restore.reassemble(mirror, receipt, restore.digest(receipt), tmp_path / "understated")
    assert not (tmp_path / "understated/image-restore-result.json").exists()
