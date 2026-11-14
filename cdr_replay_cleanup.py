"""Bounded replay cleanup anchored to a verified POSIX directory descriptor."""
import os
import stat


def cleanup(root, identity, allowed):
    if os.name != 'posix':
        # Windows path deletion cannot preserve a directory-fd binding. Retain
        # finite scratch explicitly; its owning experiment must account for it.
        return dict(state='RETAINED_UNSUPPORTED_ANCHORED_DELETE', path=str(root))
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != identity:
            raise RuntimeError('owned replay directory changed before cleanup')
        names = os.listdir(descriptor)
        if len(names) > len(allowed) or any(name not in allowed for name in names):
            raise RuntimeError('unknown replay cleanup entry')
        entries = {}
        for name in names:
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeError('unsafe replay cleanup entry')
            entries[name] = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        for name in names:
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if entries[name] != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns):
                raise RuntimeError('replay cleanup entry changed')
            os.unlink(name, dir_fd=descriptor)
        if os.listdir(descriptor):
            raise RuntimeError('new replay cleanup entry appeared')
        current = root.lstat()
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != identity:
            raise RuntimeError('owned replay directory pathname changed during cleanup')
        # Never pathname-rmdir: the original name may now denote another tree.
        return dict(state='FILES_REMOVED_EMPTY_DIRECTORY_RETAINED', path=str(root), files=len(names))
    finally:
        os.close(descriptor)
