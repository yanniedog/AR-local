"""Exercise the actual trusted install inventory without a checkout import fallback."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from tests.test_ar_local_restore_integrity import _file_hashes, _write_current_finalized
from tests.test_pi_backup_foundation import _write_finalized_observation

ROOT = Path(__file__).resolve().parents[1]


def _install_inventory() -> set[str]:
    installer = (ROOT / "deploy/pi/install-backup-foundation.sh").read_text(encoding="utf-8")
    trusted = installer.split('trusted="/usr/local/lib/ar-local-backup"', 1)[1]
    python_loop = trusted.split("for name in \\\n", 1)[1].split("\ndo", 1)[0]
    modules = set(re.findall(r"\b\w+\.py\b", python_loop))
    schema_loop = trusted.split("for name in export-contract-v2.schema.json", 1)[1].split("; do", 1)[0]
    schemas = {"contracts/export-contract-v2.schema.json", *(f"contracts/{name}" for name in re.findall(r"[\w-]+\.schema\.json", schema_loop))}
    hashed = set(re.findall(r"[\w/-]+(?:\.py|\.schema\.json)", trusted.split("sha256sum \\\n", 1)[1].split('\n) > "$tmp/backup-gate.sha256"', 1)[0]))
    assert modules | schemas == hashed, "Installed and hash-bound inventories must agree"
    return modules | schemas


def test_installed_bundle_verifies_canonical_legacy_and_wal_without_repo_imports(tmp_path: Path):
    bundle = tmp_path / "trusted"
    for relative in _install_inventory():
        destination = bundle / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    canonical, legacy, wal = (tmp_path / name for name in ("canonical", "legacy", "wal"))
    _write_current_finalized(canonical)
    _write_finalized_observation(legacy)
    _write_finalized_observation(wal)
    database = wal / "state/secondary.sqlite"
    with closing(sqlite3.connect(database)) as writer:
        writer.executescript("CREATE TABLE parent(id INTEGER PRIMARY KEY); CREATE TABLE child(parent_id INTEGER REFERENCES parent(id));")
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO child VALUES (99)")
        writer.commit()
        before = {str(root): _file_hashes(root) for root in (canonical, legacy, wal)}
        script = """
import json, sys
from pathlib import Path
bundle = Path(sys.argv[1]).resolve()
repo = Path(sys.argv[2]).resolve()
assert all(not value or Path(value).resolve() != repo for value in sys.path)
import ar_local_restore_verification as verifier
assert Path(verifier.__file__).resolve().parent == bundle
reports = [verifier.verify_restored_state(Path(value)) for value in sys.argv[3:]]
assert reports[0]['ok'], reports[0]['findings']
assert reports[0]['selected_observation']['observation_state'] == 'partial'
assert reports[1]['ok'], reports[1]['findings']
assert not reports[2]['ok']
assert any(value.startswith('sqlite_foreign_key_check:') for value in reports[2]['findings'])
for module in tuple(sys.modules.values()):
    location = getattr(module, '__file__', None)
    assert not location or not Path(location).resolve().is_relative_to(repo), location
print(json.dumps({'canonical': reports[0]['ok'], 'legacy': reports[1]['ok'], 'wal_orphan_rejected': not reports[2]['ok']}))
"""
        environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-c", script, str(bundle), str(ROOT), str(canonical), str(legacy), str(wal)],
            cwd=bundle, env=environment, capture_output=True, text=True, timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout) == {"canonical": True, "legacy": True, "wal_orphan_rejected": True}
        assert {str(root): _file_hashes(root) for root in (canonical, legacy, wal)} == before
