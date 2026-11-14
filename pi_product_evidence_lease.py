"""Ordinary parent-owned publication lease; ambiguous cleanup remains manual.

No stale recovery, new queue claim, host lease or process-local lock API change.
The child only reads the record. Its read-only state mount remains unchanged.
"""
import hashlib
import os
from pathlib import Path
import stat

from ar_local_backup_policy import fsync_directory
from app_payload_product_evidence_contract import require
from pi_product_evidence_launch import publication_record,ticks,group


class PublicationLease:
    def __init__(self,state,attempt,owner):
        self.path=Path(state)/'daily-ingest.lock';self.attempt=attempt;self.owner=owner;self.fd=None
        self.proof=None;self.body=None

    def __enter__(self):
        pid=os.getpid();job=self.owner['job']
        require(group(pid)==job['cgroup'],'publication parent is outside original claim')
        boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        require(boot==job['boot_id'],'publication parent boot changed')
        # Any existing manual, stale or unfamiliar record is occupied. Optional
        # work never renames, recovers or removes an incumbent production owner.
        fd=os.open(self.path,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        self.fd=fd
        try:
            self.body=publication_record(pid,boot,self.attempt['attempt_id'])
            require(os.write(fd,self.body)==len(self.body),'short publication lease write')
            os.fsync(fd);fsync_directory(self.path.parent);info=os.fstat(fd)
            self.proof=dict(schema='ar-product-evidence-parent-lease-v1',pid=pid,start_ticks=ticks(pid),fd=fd,
                device=info.st_dev,inode=info.st_ino,boot_id=boot,cgroup=job['cgroup'],record_sha256=hashlib.sha256(self.body).hexdigest())
            self.verify();return self
        except BaseException:
            os.close(fd);self.fd=None  # Preserve even an incomplete manual obligation.
            raise

    def verify(self):
        require(self.fd is not None and self.proof is not None and os.getpid()==self.proof['pid'],'publication lease is not retained')
        held=os.fstat(self.fd);named=self.path.lstat()
        require(stat.S_ISREG(named.st_mode) and (held.st_dev,held.st_ino)==(named.st_dev,named.st_ino)==
                (self.proof['device'],self.proof['inode']) and held.st_nlink==named.st_nlink==1,'publication lease replaced')
        os.lseek(self.fd,0,os.SEEK_SET)
        require(os.read(self.fd,16385)==self.body,'publication lease bytes changed')
        return dict(self.proof)

    def release(self,*,owned_group_empty):
        require(owned_group_empty is True,'unknown child cleanup retains manual publication lease')
        self.verify()
        self.path.unlink();fsync_directory(self.path.parent)

    def __exit__(self,*_):
        # Unlink is an explicit post-terminal action, never an exception finalizer.
        if self.fd is not None:os.close(self.fd);self.fd=None
