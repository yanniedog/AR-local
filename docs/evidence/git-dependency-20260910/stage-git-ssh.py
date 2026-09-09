"""Stage Git for Windows' authenticated SSH runtime, without an installer."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import zipfile

tools = Path(r'C:\code\backups\AR-local-user-session\tools')
source = tools / 'Git-2.55.0.5-64-bit.tar.bz2'
expected = '58fdf5679db11901697d2257cd076c8cdc49d64fe641b3e64ad158f1c5bf9b8d'
assert hashlib.sha256(source.read_bytes()).hexdigest() == expected
root = tools / 'git-ssh-2.55.0.5'
root.mkdir(exist_ok=False)
archive = tools / 'git-ssh-2.55.0.5-verified.zip'
manifest = []
with tarfile.open(source) as tar, zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as out:
    for item in tar:
        if not item.isfile() or not item.name.startswith(('usr/bin/', 'etc/')):
            continue
        name = PurePosixPath(item.name)
        assert not name.is_absolute() and '..' not in name.parts and ':' not in item.name
        raw = tar.extractfile(item).read()
        target = root / item.name
        assert root in target.resolve().parents
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)
        out.writestr(item.name, raw)
        manifest.append({'path': item.name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
assert (root / 'usr/bin/ssh.exe').is_file() and (root / 'usr/bin/scp.exe').is_file()
record = {'upstream_url': 'https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.5/Git-2.55.0.5-64-bit.tar.bz2',
          'upstream_sha256': expected, 'archive': str(archive),
          'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
          'root': str(root), 'files': manifest,
          'selection': 'Regular usr/bin and etc files only; no installer or link extraction'}
with (Path(__file__).parent / 'git-ssh-package.json').open('x', encoding='utf-8') as output:
    json.dump(record, output, indent=2)
print(json.dumps({k: v for k, v in record.items() if k != 'files'} | {'file_count': len(manifest)}))
