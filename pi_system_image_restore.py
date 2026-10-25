"""Reassemble verified keyless image frames into a NEW private regular .img.

Reads a downloaded image-object mirror. No upload, device, overwrite or flashing
mode exists. Requires the repository's pinned zstandard dependency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path

import zstandard
from pi_system_sparse import allocation_bound, enable_sparse, sparse_write


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def regular(path):
    path = Path(path)
    info = path.lstat()
    if path.resolve() != path or not stat.S_ISREG(info.st_mode):
        raise ValueError("image input must be a canonical regular file")
    return info


def windows_private_directory(path):
    """Create with protected user/SYSTEM DACL before any image bytes exist."""
    import ctypes as ct
    from ctypes import wintypes as wt
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    security = ct.WinDLL("advapi32", use_last_error=True)
    def api(dll, name, result, arguments):
        method = getattr(dll, name)
        method.restype, method.argtypes = result, arguments
        return method
    class Attributes(ct.Structure):
        _fields_ = [("length", wt.DWORD), ("descriptor", wt.LPVOID), ("inherit", wt.BOOL)]
    current = api(kernel, "GetCurrentProcess", wt.HANDLE, [])
    token_open = api(security, "OpenProcessToken", wt.BOOL, [wt.HANDLE, wt.DWORD, ct.POINTER(wt.HANDLE)])
    token_info = api(security, "GetTokenInformation", wt.BOOL, [wt.HANDLE, ct.c_int, wt.LPVOID, wt.DWORD, ct.POINTER(wt.DWORD)])
    sid_text = api(security, "ConvertSidToStringSidW", wt.BOOL, [wt.LPVOID, ct.POINTER(wt.LPWSTR)])
    descriptor = api(security, "ConvertStringSecurityDescriptorToSecurityDescriptorW", wt.BOOL, [wt.LPCWSTR, wt.DWORD, ct.POINTER(wt.LPVOID), ct.POINTER(wt.DWORD)])
    free = api(kernel, "LocalFree", wt.LPVOID, [wt.LPVOID])
    close = api(kernel, "CloseHandle", wt.BOOL, [wt.HANDLE])
    volume_path = api(kernel, "GetVolumePathNameW", wt.BOOL, [wt.LPCWSTR, wt.LPWSTR, wt.DWORD])
    volume_info = api(kernel, "GetVolumeInformationW", wt.BOOL, [wt.LPCWSTR, wt.LPWSTR, wt.DWORD, ct.POINTER(wt.DWORD), ct.POINTER(wt.DWORD), ct.POINTER(wt.DWORD), wt.LPWSTR, wt.DWORD])
    create = api(kernel, "CreateDirectoryW", wt.BOOL, [wt.LPCWSTR, ct.POINTER(Attributes)])
    token, needed, text, sd = wt.HANDLE(), wt.DWORD(), wt.LPWSTR(), wt.LPVOID()
    root, flags = ct.create_unicode_buffer(32768), wt.DWORD()
    if not volume_path(str(path.parent), root, len(root)) or not volume_info(root.value, None, 0, None, None, ct.byref(flags), None, 0):
        raise ct.WinError(ct.get_last_error())
    if not flags.value & 0x8:
        raise ValueError("image output requires persistent Windows ACLs")
    if not token_open(current(), 0x8, ct.byref(token)):
        raise ct.WinError(ct.get_last_error())
    try:
        token_info(token, 1, None, 0, ct.byref(needed))
        if not 0 < needed.value <= 65536:
            raise ValueError("invalid token user buffer")
        buffer = ct.create_string_buffer(needed.value)
        if not token_info(token, 1, buffer, needed, ct.byref(needed)) or not sid_text(ct.c_void_p.from_buffer(buffer), ct.byref(text)):
            raise ct.WinError(ct.get_last_error())
        sddl = f"D:P(A;OICI;FA;;;{text.value})(A;OICI;FA;;;SY)"
        if not descriptor(sddl, 1, ct.byref(sd), None):
            raise ct.WinError(ct.get_last_error())
        attributes = Attributes(ct.sizeof(Attributes), sd, False)
        if not create(str(path), ct.byref(attributes)):
            raise ct.WinError(ct.get_last_error())
    finally:
        if sd:
            free(sd)
        if text:
            free(ct.cast(text, wt.LPVOID))
        close(token)


def reassemble(mirror, receipt_path, receipt_sha256, workspace):
    mirror, receipt_path, workspace = map(Path, (mirror, receipt_path, workspace))
    if not mirror.is_absolute() or mirror.resolve() != mirror or not mirror.is_dir():
        raise ValueError("canonical downloaded image mirror required")
    regular(receipt_path)
    if not re.fullmatch(r"[a-f0-9]{64}", receipt_sha256) or digest(receipt_path) != receipt_sha256:
        raise ValueError("recovery-set receipt differs from independently recorded digest")
    if receipt_path.stat().st_size > 16 * 1024 ** 2:
        raise ValueError("recovery-set receipt exceeds bound")
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("schema") != "ar-local-system-recovery-set-v1" or receipt.get("result") != "IMAGE_AND_FILESYSTEM_VERIFIED" or receipt.get("compression") != "zstd-lossless-no-encryption":
        raise ValueError("unsupported or incomplete recovery set")
    parts, offset = receipt["compressed_parts"], 0
    if not isinstance(parts, list) or not 0 < len(parts) <= 8192 or not re.fullmatch(r"[a-f0-9]{64}", receipt["image_sha256"]):
        raise ValueError("invalid image frame catalog")
    for number, row in enumerate(parts, 1):
        if (row["path"] != f"recovery.img.part{number:06d}.zst" or type(row["length"]) is not int
                or not 0 < row["length"] <= 1024 ** 3 or row["offset"] != offset
                or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"]) or not re.fullmatch(r"[a-f0-9]{64}", row["image_bytes_sha256"])):
            raise ValueError("invalid image frame order, length or hash")
        path = mirror / row["path"]
        if regular(path).st_size != row["bytes"] or digest(path) != row["sha256"]:
            raise ValueError("downloaded compressed frame differs")
        offset += row["length"]
    if offset != receipt["image_bytes"]:
        raise ValueError("image byte count differs")
    if (not workspace.is_absolute() or workspace.resolve() != workspace or workspace.exists()
            or mirror == workspace or mirror in workspace.parents or workspace in mirror.parents):
        raise ValueError("new canonical private workspace outside mirror required")
    allocation = receipt.get("reassembled_allocation_bound", offset)
    if type(allocation) is not int or not 0 <= allocation <= ((offset + 65535) // 65536 + len(parts)) * 65536:
        raise ValueError("invalid sparse image allocation bound")
    if shutil.disk_usage(workspace.parent).free < allocation + 1024 ** 3:
        raise ValueError("insufficient measured space for restored image")
    if os.name == "nt":
        windows_private_directory(workspace)
    else:
        workspace.mkdir(mode=0o700)
        os.chmod(workspace, 0o700)
    image = workspace / "recovery.img"
    descriptor = os.open(image, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        enable_sparse(descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    whole = hashlib.sha256()
    allocated = 0
    with os.fdopen(descriptor, "wb") as output:
        for row in parts:
            decoded, length, part_allocated = hashlib.sha256(), 0, 0
            with (mirror / row["path"]).open("rb") as source:
                header = zstandard.get_frame_parameters(source.read(18))
                if header.window_size > 128 * 1024 ** 2:
                    raise ValueError("image zstd window exceeds bounded restore memory")
                source.seek(0)
                with zstandard.ZstdDecompressor(max_window_size=128 * 1024 ** 2).stream_reader(source) as reader:
                    while True:
                        block = reader.read(1024 * 1024)
                        if not block:
                            break
                        length += len(block)
                        if length > row["length"]:
                            raise ValueError("decompressed image exceeds declared frame length")
                        sparse_write(output, block)
                        part_allocated += allocation_bound(block)
                        if "reassembled_allocation_bound" in receipt and allocated + part_allocated > allocation:
                            raise ValueError("decompressed image exceeds sparse allocation bound")
                        decoded.update(block)
                        whole.update(block)
            if length != row["length"] or decoded.hexdigest() != row["image_bytes_sha256"]:
                raise ValueError("restored image frame length/hash differs")
            if "reassembled_allocation_bound" in row and row["reassembled_allocation_bound"] != part_allocated:
                raise ValueError("restored sparse frame allocation differs")
            allocated += part_allocated
        output.truncate(offset)
        output.flush()
        os.fsync(output.fileno())
    if whole.hexdigest() != receipt["image_sha256"] or digest(image) != whole.hexdigest():
        raise ValueError("complete ordinary image hash differs")
    result = {"result": "REGULAR_IMAGE_REASSEMBLED_VERIFIED", "image": str(image), "bytes": offset,
              "image_sha256": whole.hexdigest(), "recovery_set_sha256": receipt_sha256,
              "raw_restore_required": receipt["raw_restore_required"], "boot_test": "NOT_TESTED"}
    with (workspace / "image-restore-result.json").open("x") as stream:
        json.dump(result, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("mirror", "recovery-set", "recovery-set-sha256", "workspace"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    result = reassemble(args.mirror, args.recovery_set, args.recovery_set_sha256, args.workspace)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
