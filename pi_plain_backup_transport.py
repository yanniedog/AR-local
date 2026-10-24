"""Create-only plaintext recovery transport using the existing Drive app.

No Restic, encryption key, deletion, replacement, sync or OAuth enrollment.
Provider diagnostics stay private; stdout/stderr never contain payload data.
"""
import configparser
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import time
from pi_plain_backup_attestation import protected_file


class Rclone:
    def __init__(self, config, remote, root_folder_id, guard):
        self.config, self.remote, self.root_folder_id, self.guard = Path(config), remote, root_folder_id, guard
        self.executable = '/usr/bin/rclone'
        match = re.fullmatch(r'([a-zA-Z0-9_-]+):plaintext-recovery', remote)
        if not match or not re.fullmatch(r'[a-zA-Z0-9_-]{10,200}', root_folder_id):
            raise ValueError('approved remote and pinned Drive root folder ID required')
        info = self.config.lstat()
        if (self.config != self.config.resolve() or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1 or info.st_size > 1024**2
                or stat.S_IMODE(info.st_mode) not in (0o400, 0o440, 0o600, 0o640)
                or info.st_uid not in (0, os.getuid())):
            raise ValueError('private canonical existing rclone config required')
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(self.config, encoding='utf-8')
        section = parser[match[1]]
        if (section.get('type') != 'drive' or section.get('scope') != 'drive.file'
                or not json.loads(section.get('token', '{}')).get('refresh_token')
                or section.get('service_account_file') or section.get('service_account_credentials')
                or section.get('team_drive')
                or section.get('root_folder_id') not in (None, '', root_folder_id)):
            raise ValueError('reuse existing drive.file application credentials only')

    def path(self, relative):
        if (not re.fullmatch(r'(?:packs/[a-f0-9]{64}/(?:archive\.tar\.zst|descriptor\.json)|catalogs/[a-f0-9]{64}\.json|manifests/[a-f0-9]{64}\.jsonl)', relative)):
            raise ValueError('unsupported recovery object path')
        return self.remote + '/' + relative

    def command(self, source, destination, missing=False):
        self.guard()
        protected_file(Path(self.executable).resolve(strict=True))
        env = dict(PATH='/usr/bin:/bin', LC_ALL='C', GOMAXPROCS='2',
            GOMEMLIMIT='192MiB', GOGC='50', HOME='/nonexistent')
        args = [self.executable, '--config', str(self.config), 'copyto', source, destination,
            '--drive-root-folder-id', self.root_folder_id,
            '--immutable', '--ignore-existing', '--checksum', '--transfers', '1', '--checkers', '1',
            '--bwlimit', '8M', '--retries', '1', '--low-level-retries', '2', '--contimeout', '30s', '--timeout', '60s']
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            child = subprocess.Popen(args, stdout=out, stderr=err, env=env)
            try:
                while child.poll() is None:
                    self.guard()
                    if out.tell() + err.tell() > 256 * 1024:
                        raise RuntimeError('transport diagnostic size limit exceeded')
                    time.sleep(.1)
                self.guard()
                if missing and child.returncode in (3, 4):
                    return False
                if child.returncode:
                    raise RuntimeError('recovery transport failed: exit ' + str(child.returncode))
                return True
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill(); child.wait(timeout=10)

    def download(self, relative, destination):
        if destination.exists() or destination.is_symlink():
            raise ValueError('download requires new private destination')
        return self.command(self.path(relative), str(destination), missing=True)

    def upload(self, relative, source):
        return self.command(str(source), self.path(relative))
