"""Bounded sparse regular-file output; no device or source-disk operations."""
import os

UNIT = 65536


def allocation_bound(block):
    return sum(UNIT for start in range(0, len(block), UNIT) if block[start:start + UNIT].strip(b"\0"))


def enable_sparse(descriptor):
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        control = kernel.DeviceIoControl
        control.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                            wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        control.restype = wintypes.BOOL
        returned = wintypes.DWORD()
        if not control(msvcrt.get_osfhandle(descriptor), 0x900C4, None, 0, None, 0, ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())


def sparse_write(stream, block):
    if not block.strip(b"\0"):
        stream.seek(len(block), os.SEEK_CUR)
        return
    for start in range(0, len(block), UNIT):
        chunk = block[start:start + UNIT]
        if chunk.strip(b"\0"):
            stream.write(chunk)
        else:
            stream.seek(len(chunk), os.SEEK_CUR)
