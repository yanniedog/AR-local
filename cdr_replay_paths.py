"""Create/validate a dedicated private replay namespace without changing others."""
import os
from pathlib import Path
import re
import stat


def _windows_private(path):
    import ctypes as ct
    from ctypes import wintypes as wt
    kernel, security = ct.WinDLL('kernel32', use_last_error=True), ct.WinDLL('advapi32', use_last_error=True)
    def api(dll, name, result, args):
        method = getattr(dll, name); method.restype = result; method.argtypes = args
        return method
    current = api(kernel, 'GetCurrentProcess', wt.HANDLE, [])
    open_token = api(security, 'OpenProcessToken', wt.BOOL, [wt.HANDLE, wt.DWORD, ct.POINTER(wt.HANDLE)])
    token_info = api(security, 'GetTokenInformation', wt.BOOL, [wt.HANDLE, ct.c_int, wt.LPVOID, wt.DWORD, ct.POINTER(wt.DWORD)])
    sid_text = api(security, 'ConvertSidToStringSidW', wt.BOOL, [wt.LPVOID, ct.POINTER(wt.LPWSTR)])
    query = api(security, 'GetFileSecurityW', wt.BOOL, [wt.LPCWSTR, wt.DWORD, wt.LPVOID, wt.DWORD, ct.POINTER(wt.DWORD)])
    owner = api(security, 'GetSecurityDescriptorOwner', wt.BOOL, [wt.LPVOID, ct.POINTER(wt.LPVOID), ct.POINTER(wt.BOOL)])
    equal = api(security, 'EqualSid', wt.BOOL, [wt.LPVOID, wt.LPVOID])
    convert = api(security, 'ConvertSecurityDescriptorToStringSecurityDescriptorW', wt.BOOL,
                  [wt.LPVOID, wt.DWORD, wt.DWORD, ct.POINTER(wt.LPWSTR), ct.POINTER(wt.DWORD)])
    free = api(kernel, 'LocalFree', wt.LPVOID, [wt.LPVOID])
    close = api(kernel, 'CloseHandle', wt.BOOL, [wt.HANDLE])
    token, needed, user, text = wt.HANDLE(), wt.DWORD(), wt.LPWSTR(), wt.LPWSTR()
    if not open_token(current(), 0x8, ct.byref(token)): raise ct.WinError(ct.get_last_error())
    try:
        token_info(token, 1, None, 0, ct.byref(needed))
        if not 0 < needed.value <= 65536: raise ValueError('invalid token buffer')
        user_buffer = ct.create_string_buffer(needed.value)
        if not token_info(token, 1, user_buffer, needed, ct.byref(needed)): raise ct.WinError(ct.get_last_error())
        user_sid = ct.c_void_p.from_buffer(user_buffer)
        if not sid_text(user_sid, ct.byref(user)): raise ct.WinError(ct.get_last_error())
        query(str(path), 5, None, 0, ct.byref(needed))  # OWNER | DACL, read-only.
        if not 0 < needed.value <= 65536: raise ValueError('invalid directory security buffer')
        buffer = ct.create_string_buffer(needed.value)
        if not query(str(path), 5, buffer, needed, ct.byref(needed)): raise ct.WinError(ct.get_last_error())
        owner_sid, defaulted = wt.LPVOID(), wt.BOOL()
        if not owner(buffer, ct.byref(owner_sid), ct.byref(defaulted)) or not equal(owner_sid, user_sid):
            raise ValueError('replay namespace belongs to another Windows user')
        if not convert(buffer, 1, 4, ct.byref(text), None): raise ct.WinError(ct.get_last_error())
        value = text.value
        entries = re.findall(r'\([^()]*\)', value)
        if (value[:value.find('(')] not in ('D:P', 'D:PAI') or len(entries) != 2
                or set(entries) != {f'(A;OICI;FA;;;{user.value})', '(A;OICI;FA;;;SY)'}):
            raise ValueError('replay namespace DACL is not protected user/SYSTEM only')
    finally:
        if user: free(ct.cast(user, wt.LPVOID))
        if text: free(ct.cast(text, wt.LPVOID))
        close(token)


def private_replay_parent(supplied):
    path = Path(supplied).absolute()
    if path.resolve() != path: raise ValueError('canonical replay namespace required')
    for parent in (path, *path.parents):
        if not parent.exists() and not parent.is_symlink(): continue
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or parent.is_symlink()
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise ValueError('replay namespace has unsafe directory/reparse ancestry')
    if not path.parent.is_dir(): raise ValueError('replay namespace parent must already exist')
    if not path.exists():
        from pi_plain_backup_restore import private_workspace
        private_workspace(path)
    before = path.lstat()
    if os.name == 'nt':
        _windows_private(path)
    elif before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) & 0o077:
        raise ValueError('replay namespace must be owned and private')
    after = path.lstat()
    if (before.st_dev, before.st_ino, before.st_mode) != (after.st_dev, after.st_ino, after.st_mode):
        raise ValueError('replay namespace changed during validation')
    return path
