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
