"""Portable syscall seam; never evidence of kernel cache qualification."""
import os
from types import SimpleNamespace

import pytest
import pi_cdr_quality_read_io as read_io


@pytest.fixture(autouse=True)
def dropbehind_syscall_contract(monkeypatch):
    def preadv(fd, vectors, offset, flags):
        assert flags == 0x80
        if hasattr(os, "pread"):
            block = os.pread(fd, len(vectors[0]), offset)
        else:
            previous = os.lseek(fd, 0, os.SEEK_CUR)
            try:
                os.lseek(fd, offset, os.SEEK_SET)
                block = os.read(fd, len(vectors[0]))
            finally:
                os.lseek(fd, previous, os.SEEK_SET)
        vectors[0][:len(block)] = block
        return len(block)
    monkeypatch.setattr(read_io, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(read_io, "os", SimpleNamespace(preadv=preadv))
