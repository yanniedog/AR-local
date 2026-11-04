"""File-level Raspberry Pi recovery capture; writes only a new private workspace.

Use read-only source mounts supplied by a reviewed operator namespace. Baseline
copy is online; finalize runs during an independently controlled application
quiescence. Archives are made from the resulting private, frozen copies. This is
not a claim of an atomic whole-host block snapshot. No Drive writes occur here.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from pi_system_filesystems import source_fat

SCHEMA = "ar-local-system-capture-v1"
RUNTIME = {"dev", "proc", "sys", "run", "tmp"}
DATA_PREFIX = "srv/ar-local/data/"
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == "posix":
        descriptor = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def relative(value):
    path = PurePosixPath(value)
    if not value or value == "." or path.is_absolute() or str(path) != value or any(part in {".", ".."} for part in path.parts):
        raise ValueError("noncanonical relative path")
    return value


def canonical(path):
    path = Path(path)
    if not path.is_absolute() or str(path) != os.path.normpath(path) or path.resolve() != path:
        raise ValueError("path must be canonical, absolute and not symlinked")
    return path


def source_view(path):
    path = canonical(path)
    if not path.is_dir() or not os.statvfs(path).f_flag & os.ST_RDONLY:
        raise ValueError("source must be an existing read-only mount view")
    return path


def fingerprint(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_uid, info.st_gid, info.st_nlink]


def inventory(root, *, skip=(), sort_path, starts=(".",)):
    """Walk one persistent filesystem, never following symlinks or mount trees."""
    root = Path(root)
    device = root.stat().st_dev
    descriptor = os.open(sort_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    queue = sqlite3.connect(sort_path)
    queue.execute("PRAGMA cache_size=-8192")
    queue.execute("PRAGMA temp_store=FILE")
    queue.execute("CREATE TABLE queue(id INTEGER PRIMARY KEY,path TEXT,done INTEGER DEFAULT 0)")
    queue.execute("CREATE INDEX pending ON queue(done,id)")
    queue.execute("CREATE TABLE children(name BLOB PRIMARY KEY)")
    for name in starts:
        if name != ".":
            relative(name)
        if (root / name).exists() or (root / name).is_symlink():
            queue.execute("INSERT INTO queue(path) VALUES (?)", (name,))
    try:
        while True:
            pending = queue.execute("SELECT id,path FROM queue WHERE done=0 ORDER BY id LIMIT 1").fetchone()
            if not pending:
                break
            identifier, name = pending
            queue.execute("UPDATE queue SET done=1 WHERE id=?", (identifier,))
            path = root if name == "." else root / name
            info = path.lstat()
            yield name, path, info
            if not stat.S_ISDIR(info.st_mode) or name in skip:
                continue
            if info.st_dev != device:
                raise ValueError("unexpected persistent mount requires separate coverage: " + name)
            queue.execute("DELETE FROM children")
            with os.scandir(path) as children:
                for child in children:
                    queue.execute("INSERT INTO children VALUES (?)", (os.fsencode(child.name),))
            for child, in queue.execute("SELECT name FROM children ORDER BY name"):
                child_name = os.fsdecode(child) if name == "." else name + "/" + os.fsdecode(child)
                queue.execute("INSERT INTO queue(path) VALUES (?)", (child_name,))
    finally:
        queue.close()
        Path(sort_path).unlink()


def raw_index(work, catalog_path, catalog_sha, index_path):
    if sha(catalog_path) != catalog_sha:
        raise ValueError("raw cloud catalog hash differs")
    catalog = json.loads(Path(catalog_path).read_text())
    descriptor = catalog["file_index"]
    if descriptor["schema"] != "ar-local-plain-file-index-v1" or descriptor["data_root"] != "/srv/ar-local/data":
        raise ValueError("unsupported raw catalog index")
    if sha(index_path) != descriptor["sha256"] or Path(index_path).stat().st_size != descriptor["bytes"]:
        raise ValueError("raw index hash/size differs from cloud catalog")
    database = sqlite3.connect(work / "external-index.sqlite")
    database.execute("CREATE TABLE files(path TEXT PRIMARY KEY, row_json TEXT NOT NULL)")
    count = 0
    with Path(index_path).open(encoding="utf-8") as stream:
        header = json.loads(next(stream))
        if header != {"schema": descriptor["schema"], "data_root": descriptor["data_root"]}:
            raise ValueError("raw index header differs")
        for line in stream:
            row = json.loads(line)
            name = relative(row["source_relative"])
            count += 1
            if (row["representation"] == "exact_source_bytes"
                    and name.split("/", 1)[0] in {"runs", "runs-archive"}):
                database.execute("INSERT INTO files VALUES (?,?)", (DATA_PREFIX + name, json.dumps(row)))
    if count != descriptor["records"]:
        raise ValueError("raw index record count differs")
    database.commit()
    return database, {"catalog_sha256": catalog_sha, "file_index": descriptor,
                      "catalog": catalog, "index_records": count}


def external_match(path, info, name, database, previous=None):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        return None
    result = database.execute("SELECT row_json FROM files WHERE path=?", (name,)).fetchone()
    if not result:
        return None
    row = json.loads(result[0])
    fields = {"size": info.st_size, "mtime_ns": info.st_mtime_ns,
              "uid": info.st_uid, "gid": info.st_gid}
    mode = int(row["mode"], 0) if isinstance(row["mode"], str) else row["mode"]
    if mode != stat.S_IMODE(info.st_mode):
        return None
    if any(row[key] != value for key, value in fields.items()):
        return None
    # A previous content hash remains valid only for this exact inode/ctime and
    # metadata. Changed raw data is rehashed and retained in the OS layer if it
    # no longer matches. No ancestor-only exclusion can omit an unknown file.
    if not previous or previous.get("source") != fingerprint(info):
        if sha(path) != row["sha256"] or fingerprint(path.lstat()) != fingerprint(info):
            return None
    return {**row, "source": fingerprint(info), "restore_xattrs": {
        key: base64.b64encode(os.getxattr(path, key, follow_symlinks=False)).decode("ascii")
        for key in sorted(os.listxattr(path, follow_symlinks=False))}}


def run(argv, **kwargs):
    subprocess.run(list(map(str, argv)), check=True, env=ENV, shell=False, **kwargs)


def workspace(path):
    path = canonical(path)
    if (not stat.S_ISDIR(path.lstat().st_mode) or path.stat().st_mode & 0o077
            or path.stat().st_uid != os.geteuid()):
        raise ValueError("workspace must be private mode 0700")
    value = json.loads((path / "workspace.json").read_text())
    if value["schema"] != SCHEMA or value["workspace"] != str(path):
        raise ValueError("workspace identity differs")
    return path, value


def source_listing(work, settings, phase, *, starts=None, skip_extra=()):
    os.environ["SQLITE_TMPDIR"] = str(work)
    database = sqlite3.connect(work / "inventory.sqlite")
    database.execute("PRAGMA cache_size=-8192")
    database.execute("PRAGMA temp_store=FILE")
    database.execute("CREATE TABLE IF NOT EXISTS entries(phase TEXT, tree TEXT, path TEXT, value TEXT, PRIMARY KEY(phase,tree,path))")
    database.execute("CREATE TABLE IF NOT EXISTS links(phase TEXT,tree TEXT,dev INTEGER,ino INTEGER,path TEXT,PRIMARY KEY(phase,tree,path))")
    database.execute("CREATE INDEX IF NOT EXISTS link_inodes ON links(phase,tree,dev,ino,path)")
    raw = sqlite3.connect(work / "external-index.sqlite")
    omitted = 0
    for tree in ("root", "boot"):
        source = source_view(settings[tree])
        skip = RUNTIME | {"boot/firmware", settings["workspace_source_relative"]} | set(skip_extra) if tree == "root" else set()
        roots = (".", *starts) if tree == "root" and starts else (".",)
        if tree == "root" and starts:
            skip.add(".")  # Capture root directory attributes without a second full walk.
        with (work / (phase + "-" + tree + ".files")).open("xb") as files:
            for name, path, info in inventory(source, skip=skip, starts=roots, sort_path=work / (phase + "-" + tree + "-walk.sqlite")):
                if name in skip_extra:
                    continue
                if stat.S_ISSOCK(info.st_mode):
                    # Live sockets have no recoverable queued stream. Their
                    # paths are explicitly retained as volatile exclusions.
                    value = {"source": fingerprint(info), "volatile_socket": True}
                else:
                    before = database.execute("SELECT value FROM entries WHERE phase='baseline' AND tree=? AND path=?", (tree, name)).fetchone()
                    previous = json.loads(before[0]).get("external") if before else None
                    external = external_match(path, info, name, raw, previous) if tree == "root" else None
                    value = {"source": fingerprint(info), "external": external}
                    if external:
                        omitted += 1
                    else:
                        files.write(os.fsencode(name) + b"\0")
                        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
                            database.execute("INSERT INTO links VALUES (?,?,?,?,?)", (phase, tree, info.st_dev, info.st_ino, name))
                database.execute("INSERT OR REPLACE INTO entries VALUES (?,?,?,?)", (phase, tree, name, json.dumps(value)))
        database.commit()
    raw.close()
    database.close()
    return omitted


def null_names(path):
    pending = b""
    with Path(path).open("rb") as stream:
        while True:
            block = stream.read(65536)
            if not block:
                if pending:
                    raise ValueError("truncated NUL file list")
                break
            fields = (pending + block).split(b"\0")
            pending = fields.pop()
            yield from fields


def copy_batches(work, settings, tree, names, label):
    batch = []
    number = 0
    for name in names:
        batch.append(name)
        if len(batch) == 4096:
            number += 1
            copy_batch(work, settings, tree, batch, label + str(number))
            batch.clear()
    if batch:
        copy_batch(work, settings, tree, batch, label + str(number + 1))


def copy_batch(work, settings, tree, names, label, attempt=0):
    path = work / (label + "-" + tree + ".batch")
    with path.open("xb") as stream:
        for name in names:
            stream.write(name + b"\0")
    before = {os.fsdecode(name): fingerprint((Path(settings[tree]) / os.fsdecode(name)).lstat()) for name in names}
    database = sqlite3.connect(work / "inventory.sqlite")
    phase = next(name for name in ("baseline", "prepared", "final") if label.startswith(name))
    for name, signature in before.items():
        baseline = database.execute("SELECT value FROM entries WHERE phase='baseline' AND tree=? AND path=?", (tree, name)).fetchone()
        target = work / "frozen" / tree / name
        # Changed inode/ctime must not be skipped merely because its size and
        # mtime were restored to the old values. Force recopy in private staging.
        if (attempt or (phase != "baseline" and baseline and json.loads(baseline[0])["source"] != signature)) and stat.S_ISREG(signature[2]):
            if target.is_file() or target.is_symlink():
                target.unlink()
    # -H is intentionally absent: its process-global inode table would scale
    # with millions of source files. Cross-batch links are repaired on disk.
    run(["/usr/bin/rsync", "-aAXS", "--numeric-ids", "--dirs", "--no-recursive", "--from0",
         "--files-from=" + str(path), "--", settings[tree] + "/", str(work / "frozen" / tree) + "/"])
    path.unlink()  # Only this newly created private batch list, never source.
    changed = []
    for name, signature in before.items():
        after = fingerprint((Path(settings[tree]) / name).lstat())
        value = json.loads(database.execute("SELECT value FROM entries WHERE phase=? AND tree=? AND path=?", (phase, tree, name)).fetchone()[0])
        value.update(copy_source_before=signature, copy_source_after=after, copy_observed_at=utc())
        database.execute("UPDATE entries SET value=? WHERE phase=? AND tree=? AND path=?", (json.dumps(value), phase, tree, name))
        if signature != after and not stat.S_ISDIR(signature[2]):
            changed.append(os.fsencode(name))
    database.commit()
    database.close()
    if changed:
        if attempt >= 2:
            raise ValueError("source files did not stabilize during bounded private copy")
        copy_batch(work, settings, tree, changed, label + "-retry", attempt + 1)


def repair_hardlinks(work, phase, tree):
    database = sqlite3.connect(work / "inventory.sqlite")
    database.execute("PRAGMA cache_size=-8192")
    database.execute("PRAGMA temp_store=FILE")
    previous = None
    canonical = None
    canonical_sha = None
    for device, inode, name in database.execute("SELECT dev,ino,path FROM links WHERE phase=? AND tree=? ORDER BY dev,ino,path", (phase, tree)):
        path = work / "frozen" / tree / name
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("hardlink staging target is not a regular file")
        if (device, inode) != previous:
            previous, canonical, canonical_sha = (device, inode), path, sha(path)
        elif path.stat().st_ino != canonical.stat().st_ino:
            if sha(path) != canonical_sha:
                raise ValueError("hardlinked source changed during copy")
            path.unlink()
            os.link(canonical, path, follow_symlinks=False)
    database.close()


def restore_runtime_directories(work, packages):
    rows = packages["runtime_directories_before_mask"]
    if set(rows) != RUNTIME:
        raise ValueError("complete root-parent runtime directory metadata required")
    root = work / "frozen/root"
    for name, row in rows.items():
        path = root / name
        if not path.is_dir() or path.is_symlink() or path.resolve() != path:
            raise ValueError("runtime metadata target must remain a private staged directory")
        os.chown(path, row["uid"], row["gid"], follow_symlinks=False)
        os.chmod(path, row["mode"], follow_symlinks=False)
        for key in set(os.listxattr(path, follow_symlinks=False)) - set(row["xattrs"]):
            os.removexattr(path, key, follow_symlinks=False)
        for key, value in row["xattrs"].items():
            os.setxattr(path, key, base64.b64decode(value, validate=True), follow_symlinks=False)
        os.utime(path, ns=(path.stat().st_atime_ns, row["mtime_ns"]), follow_symlinks=False)


def copy_phase(work, settings, phase):
    for tree in ("root", "boot"):
        destination = work / "frozen" / tree
        destination.mkdir(parents=True, exist_ok=True)
        copy_batches(work, settings, tree, null_names(work / (phase + "-" + tree + ".files")), phase)
        repair_hardlinks(work, phase, tree)
        database = sqlite3.connect(work / "inventory.sqlite")
        database.execute("PRAGMA temp_store=FILE")
        directory_list = work / (phase + "-" + tree + ".directories")
        with directory_list.open("xb") as stream:
            # The final table also retains the online-prepared paths. Only
            # directories visited in this phase need their attributes reset.
            for name in null_names(work / (phase + "-" + tree + ".files")):
                value = database.execute("SELECT value FROM entries WHERE phase=? AND tree=? AND path=?", (phase, tree, os.fsdecode(name))).fetchone()[0]
                if stat.S_ISDIR(json.loads(value)["source"][2]):
                    stream.write(name + b"\0")
        database.close()
        copy_batches(work, settings, tree, null_names(directory_list), phase + "-directories")


def capacity_preflight(work, phase):
    """Measure indexed source bytes before copying any payload into staging."""
    database = sqlite3.connect(work / "inventory.sqlite")
    source_bytes, entries, metadata_bytes = 0, 0, 0
    for tree, name, serialized in database.execute("SELECT tree,path,value FROM entries WHERE phase=?", (phase,)):
        row = json.loads(serialized)
        if row.get("external") or row.get("volatile_socket"):
            continue
        entries += 1
        metadata_bytes += len(serialized.encode("ascii")) + len(os.fsencode(name))
        info = row["source"]
        if stat.S_ISREG(info[2]):
            first = database.execute("SELECT MIN(path) FROM links WHERE phase=? AND tree=? AND dev=? AND ino=?", (phase, tree, info[0], info[1])).fetchone()[0] if info[8] > 1 else name
            if name == first:
                source_bytes += info[3]
    database.close()
    image_bound = source_bytes * 13 // 10 + max(3 * 1024 ** 3, entries * 1024) + 512 * 1024 ** 2
    archive_bound = source_bytes + metadata_bytes * 3 + entries * 4096
    reserve = max(10 * 1024 ** 3, (source_bytes + image_bound) // 20)
    needed = source_bytes + archive_bound + image_bound * 2 + reserve
    available = shutil.disk_usage(work).free
    result = {"result": "PASS" if available >= needed else "INSUFFICIENT_CAPACITY", "phase": phase,
              "source_private_bytes": source_bytes, "entries": entries, "archive_bound": archive_bound,
              "image_bound": image_bound, "reserve": reserve, "required_free_bytes": needed,
              "available_bytes": available, "measured_at": utc(), "external_raw_bytes_not_duplicated": True}
    write(work / (phase + "-capacity.json"), result)
    if result["result"] != "PASS":
        raise ValueError("measured capacity cannot retain staging, archives, image and compressed image safely")
    if os.name == "posix" and os.statvfs(work).f_favail < entries + 100000:
        raise ValueError("insufficient free filesystem inodes for private staging")
    return result


def baseline(args):
    work = canonical(args.workspace)
    packages = package_proof(args.package_proof)
    if work.exists():
        existing = list(work.iterdir())
        allowed = work / "baseline-package-proof.json"
        if (not work.is_dir() or work.stat().st_uid != os.geteuid() or work.stat().st_mode & 0o077
                or (existing and (existing != [allowed] or sha(allowed) != sha(args.package_proof)))):
            raise ValueError("baseline requires a new empty private workspace")
    else:
        work.mkdir(mode=0o700)
    root, boot = source_view(args.root), source_view(args.boot)
    excluded = relative(args.workspace_source_relative)
    alias = root / excluded
    if (alias.stat().st_dev, alias.stat().st_ino) != (work.stat().st_dev, work.stat().st_ino):
        raise ValueError("workspace exclusion must identify precisely this new workspace")
    settings = {"schema": SCHEMA, "workspace": str(work), "root": str(root), "boot": str(boot),
                "workspace_source_relative": excluded, "started_at": utc(), "layout": json.loads(Path(args.layout).read_text()),
                "baseline_packages": packages}
    settings["layout"]["boot_mount"] = source_fat(boot)
    database, cloud = raw_index(work, args.catalog, args.catalog_sha256, args.file_index)
    database.close()
    settings["external_recovery"] = cloud
    write(work / "workspace.json", settings)
    omitted = source_listing(work, settings, "baseline")
    capacity_preflight(work, "baseline")
    copy_phase(work, settings, "baseline")
    restore_runtime_directories(work, packages)
    write(work / "baseline.json", {"result": "BASELINE_NOT_RECOVERABLE", "finished_at": utc(), "external_files": omitted})


def package_proof(path):
    path = Path(path)
    receipt = json.loads(path.read_text())
    if (path.stat().st_uid != 0 or path.stat().st_mode & 0o222
            or receipt.get("schema") != "ar-local-package-quiescence-v1"
            or receipt.get("result") != "NATIVE_PACKAGE_LOCKS_HELD"
            or receipt.get("boot_id") != Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            or len(receipt.get("locks", [])) != 4
            or not receipt.get("units") or any(state not in {"inactive", "failed"} for state in receipt["units"].values())):
        raise ValueError("protected root-parent package lock proof required")
    return {"proof_sha256": sha(path), "dpkg_status_sha256": receipt["dpkg_status_sha256"],
            "runtime_directories_before_mask": receipt["runtime_directories_before_mask"],
            "units": receipt["units"], "locks": receipt["locks"], "boot_id": receipt["boot_id"]}


def quiescence(path):
    receipt = json.loads(Path(path).read_text())
    if (receipt.get("schema") != "ar-local-system-quiescence-v1" or receipt.get("result") != "QUIESCED"
            or receipt.get("boot_id") != Path("/proc/sys/kernel/random/boot_id").read_text().strip()):
        raise ValueError("current operator quiescence receipt required")
    expiry = datetime.fromisoformat(receipt["expires_at"])
    if expiry.utcoffset() is None or expiry <= datetime.now(timezone.utc):
        raise ValueError("quiescence receipt expired")
    units = receipt["application_writers"]
    if not units or len(units) != len(set(units)):
        raise ValueError("explicit application writer inventory required")
    states = receipt["observed_states"]
    if set(states) != set(units):
        raise ValueError("root launcher observations do not cover every application writer")
    if Path(path).stat().st_uid != 0 or Path(path).stat().st_mode & 0o222:
        raise ValueError("root launcher receipt must be protected read-only")
    for unit in units:
        if not isinstance(unit, str) or not unit.endswith((".service", ".timer")) or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@_.:-" for c in unit):
            raise ValueError("invalid writer unit identity")
        state = states[unit]
        if state not in {"inactive", "failed"}:
            raise ValueError("application writer not quiesced: " + unit)
        states[unit] = state
    return {"receipt_sha256": sha(path), "observed_at": utc(), "states": states,
            "running_infrastructure": receipt["running_infrastructure"], "writer_inventory_sha256": receipt["writer_inventory_sha256"]}


def remove_obsolete_stage_entries(work, previous="baseline", current="final"):
    database = sqlite3.connect(work / "inventory.sqlite")
    rows = database.execute("SELECT tree,path FROM entries WHERE phase=? ORDER BY length(path) DESC", (previous,))
    for tree, name in rows:
        found = database.execute("SELECT value FROM entries WHERE phase=? AND tree=? AND path=?", (current, tree, name)).fetchone()
        old = database.execute("SELECT value FROM entries WHERE phase=? AND tree=? AND path=?", (previous, tree, name)).fetchone()
        same_type = found and stat.S_IFMT(json.loads(found[0])["source"][2]) == stat.S_IFMT(json.loads(old[0])["source"][2])
        if found and same_type and not (json.loads(found[0]).get("external") or json.loads(found[0]).get("volatile_socket")):
            continue
        if name == ".":
            raise ValueError("cannot remove staging root")
        path = work / "frozen" / tree / name
        for parent in path.parents:
            if parent == work:
                break
            if parent.is_symlink():
                raise ValueError("staging cleanup ancestor became a symlink")
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists():
            path.rmdir()
    database.close()


def prepare(args):
    """Refresh the complete online copy before any application pause."""
    work, settings = workspace(args.workspace)
    packages = package_proof(args.package_proof)
    started = utc()
    source_listing(work, settings, "prepared")
    capacity_preflight(work, "prepared")
    remove_obsolete_stage_entries(work, current="prepared")
    copy_phase(work, settings, "prepared")
    restore_runtime_directories(work, packages)
    database = sqlite3.connect(work / "inventory.sqlite")
    database.execute("INSERT INTO entries SELECT 'final',tree,path,value FROM entries WHERE phase='prepared'")
    database.commit()
    database.close()
    write(work / "prepared.json", {"result": "PREPARED_NOT_RECOVERABLE", "started_at": started, "finished_at": utc(), "packages": packages})


def mutable_scope(receipt, root):
    """Require every writer's data plus the host's standard mutable locations."""
    required = {"etc", "var", "home", "root", "srv", "opt", "usr/local"}
    supplied = {relative(name) for name in receipt["mutable_paths"]}
    if any(not any(name == scope or name.startswith(scope + "/") for scope in supplied) for name in required):
        raise ValueError("mutable scope must include /etc /var /home /root /srv /opt /usr/local")
    supplied = {name for name in supplied if not any(name.startswith(other + "/") for other in supplied if name != other)}
    writers = receipt["writer_paths"]
    if set(writers) != set(receipt["application_writers"]):
        raise ValueError("every application writer requires an explicit filesystem scope")
    for paths in writers.values():
        if not paths or any(not any(relative(path) == scope or path.startswith(scope + "/") for scope in supplied) for path in paths):
            raise ValueError("application writer path is outside mutable scope")
    # Unknown top-level entries are refreshed as mutable, never silently
    # assumed immutable. Standard OS package trees retain an explicitly older
    # online capture window; package operations must be admitted separately.
    online = {"usr", "bin", "lib", "lib64", "sbin", "boot"}
    for child in Path(root).iterdir():
        if child.name not in RUNTIME | online and not any(child.name == name or child.name.startswith(name + "/") for name in supplied):
            supplied.add(child.name)
    for name in online:
        evidence = receipt["online_os_capture"].get(name)
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("explicit online OS capture classification required: " + name)
    return sorted(supplied)


def clear_mutable_entries(work, scopes):
    database = sqlite3.connect(work / "inventory.sqlite")
    group, classes = None, set()
    for device, inode, name in database.execute("SELECT dev,ino,path FROM links WHERE phase='prepared' AND tree='root' ORDER BY dev,ino,path"):
        if group != (device, inode):
            group, classes = (device, inode), set()
        classes.add(any(name == scope or name.startswith(scope + "/") for scope in scopes))
        if len(classes) > 1:
            raise ValueError("hardlink group crosses mutable/online OS scopes; expand the reviewed mutable scope")
    for scope in scopes:
        database.execute("DELETE FROM entries WHERE phase='final' AND tree='root' AND (path=? OR (path>=? AND path<?))", (scope, scope + "/", scope + "0"))
    database.execute("DELETE FROM entries WHERE phase='final' AND tree='boot'")
    database.commit()
    database.close()


def finalize(args):
    work, settings = workspace(args.workspace)
    before = quiescence(args.quiescence)
    packages = package_proof(args.package_proof)
    prepared = json.loads((work / "prepared.json").read_text())
    if prepared["result"] != "PREPARED_NOT_RECOVERABLE":
        raise ValueError("complete online prepare required before application pause")
    if packages["dpkg_status_sha256"] != prepared["packages"]["dpkg_status_sha256"] or packages["boot_id"] != prepared["packages"]["boot_id"]:
        raise ValueError("package state or boot changed since online preparation; new preparation required")
    plan = json.loads(Path(args.quiescence).read_text())
    scopes = mutable_scope(plan, settings["root"])
    started = utc()
    boot_before = tree_manifest(settings["boot"], work / "boot-source-before.jsonl")
    clear_mutable_entries(work, scopes)
    source_listing(work, settings, "final", starts=scopes)
    remove_obsolete_stage_entries(work, previous="prepared")
    copy_phase(work, settings, "final")
    restore_runtime_directories(work, packages)
    boot_after = tree_manifest(settings["boot"], work / "boot-source-after.jsonl")
    if boot_before != boot_after:
        raise ValueError("boot partition changed during final capture")
    after = quiescence(args.quiescence)
    database = sqlite3.connect(work / "inventory.sqlite")
    omitted = database.execute("SELECT COUNT(*) FROM entries WHERE phase='final' AND json_extract(value,'$.external') IS NOT NULL").fetchone()[0]
    database.close()
    write(work / "frozen.json", {"schema": SCHEMA, "result": "FROZEN_PRIVATE_COPY", "started_at": started,
          "finished_at": utc(), "quiescence_before": before, "quiescence_after": after,
          "external_files": omitted, "consistency": "application-quiesced-file-level; infrastructure capture window, not global atomic snapshot",
          "mutable_paths": scopes, "online_os_capture": plan["online_os_capture"], "prepared_sha256": sha(work / "prepared.json"),
          "packages": packages,
          "boot_source_unchanged": boot_before, "boot_test": "NOT_TESTED"})


def metadata(root, index_path):
    descriptor = os.open(index_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    hardlinks = sqlite3.connect(index_path)
    hardlinks.execute("PRAGMA cache_size=-8192")
    hardlinks.execute("CREATE TABLE links(dev INTEGER,ino INTEGER,path TEXT,sha TEXT,PRIMARY KEY(dev,ino))")
    try:
        yield from metadata_rows(root, hardlinks, Path(index_path).parent / ("walk-" + uuid.uuid4().hex + ".sqlite"))
    finally:
        hardlinks.close()
        Path(index_path).unlink()


def metadata_rows(root, hardlinks, walk_path):
    for name, path, info in inventory(root, sort_path=walk_path):
        row = {"path": name, "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "gid": info.st_gid,
               "mtime_ns": info.st_mtime_ns, "type": stat.S_IFMT(info.st_mode),
               "xattrs": {key: base64.b64encode(os.getxattr(path, key, follow_symlinks=False)).decode("ascii")
                          for key in sorted(os.listxattr(path, follow_symlinks=False))}}
        if stat.S_ISREG(info.st_mode):
            row.update(size=info.st_size)
            prior = hardlinks.execute("SELECT path,sha FROM links WHERE dev=? AND ino=?", (info.st_dev, info.st_ino)).fetchone() if info.st_nlink > 1 else None
            row["sha256"] = prior[1] if prior else sha(path)
            if info.st_nlink > 1:
                if prior:
                    row["hardlink_to"] = prior[0]
                else:
                    hardlinks.execute("INSERT INTO links VALUES (?,?,?,?)", (info.st_dev, info.st_ino, name, row["sha256"]))
        elif stat.S_ISLNK(info.st_mode):
            row["link"] = os.readlink(path)
        elif stat.S_ISCHR(info.st_mode) or stat.S_ISBLK(info.st_mode):
            row["rdev"] = info.st_rdev
        yield row


def tree_manifest(root, output):
    with Path(output).open("x", encoding="ascii") as stream:
        for row in metadata(root, Path(output).parent / ("links-" + uuid.uuid4().hex + ".sqlite")):
            stream.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")
    return {"sha256": sha(output), "bytes": Path(output).stat().st_size}


class CheckedReader:
    def __init__(self, stream):
        self.stream, self.digest = stream, hashlib.sha256()

    def read(self, size):
        block = self.stream.read(size)
        self.digest.update(block)
        return block


def compressed_tar(tree, manifest, output):
    with Path(output).open("xb") as destination:
        compressor = subprocess.Popen(["/usr/bin/zstd", "-T1", "-15", "--no-progress", "--stdout"],
                                      stdin=subprocess.PIPE, stdout=destination, env=ENV)
        try:
            with tarfile.open(fileobj=compressor.stdin, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                with Path(manifest).open(encoding="ascii") as stream:
                    for line in stream:
                        row = json.loads(line)
                        info = tarfile.TarInfo(row["path"])
                        info.mode, info.uid, info.gid = row["mode"], row["uid"], row["gid"]
                        seconds, nanos = divmod(row["mtime_ns"], 10 ** 9)
                        info.mtime = seconds
                        # Full binary ACL/xattr values live in the independently
                        # hashed manifest and each PAX header. Restore applies
                        # them explicitly; no lossy text encoding of ACLs.
                        info.pax_headers = {"mtime": f"{seconds}.{nanos:09d}", "ARLOCAL.metadata": json.dumps(row, sort_keys=True)}
                        kind = row["type"]
                        if kind == stat.S_IFREG:
                            if "hardlink_to" in row:
                                info.type, info.linkname = tarfile.LNKTYPE, row["hardlink_to"]
                                archive.addfile(info)
                            else:
                                info.size = row["size"]
                                with (Path(tree) / row["path"]).open("rb") as content:
                                    checked = CheckedReader(content)
                                    archive.addfile(info, checked)
                                    if checked.digest.hexdigest() != row["sha256"]:
                                        raise ValueError("private frozen file changed since manifest")
                        elif kind == stat.S_IFDIR:
                            info.type = tarfile.DIRTYPE
                            archive.addfile(info)
                        elif kind == stat.S_IFLNK:
                            info.type, info.linkname = tarfile.SYMTYPE, row["link"]
                            archive.addfile(info)
                        elif kind in {stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO}:
                            info.type = {stat.S_IFCHR: tarfile.CHRTYPE, stat.S_IFBLK: tarfile.BLKTYPE, stat.S_IFIFO: tarfile.FIFOTYPE}[kind]
                            if "rdev" in row:
                                info.devmajor, info.devminor = os.major(row["rdev"]), os.minor(row["rdev"])
                            archive.addfile(info)
                        else:
                            raise ValueError("unsupported persistent node type")
                        # TarFile normally retains every TarInfo even in stream
                        # mode. Its writing path does not need that index; disk
                        # manifests bind ordering and cross-batch hardlinks.
                        archive.members.clear()
            compressor.stdin.close()
            if compressor.wait() != 0:
                raise RuntimeError("lossless compression failed")
        finally:
            if compressor.poll() is None:
                compressor.terminate()
                compressor.wait(timeout=30)
        destination.flush()
        os.fsync(destination.fileno())
    run(["/usr/bin/zstd", "--test", str(output)])
    return {"sha256": sha(output), "bytes": Path(output).stat().st_size, "compression": "zstd-lossless-no-encryption"}


def archive_parts(tree, manifest, work, label):
    """Durable 512 MiB/4096-entry prefixes; a single large file is one part."""
    parts, rows, source_bytes, manifest_bytes = [], [], 0, 0
    with Path(manifest).open(encoding="ascii") as stream:
        for line in stream:
            row = json.loads(line)
            size = row.get("size", 0) if "hardlink_to" not in row else 0
            if rows and (len(rows) >= 4096 or source_bytes + size > 512 * 1024 ** 2 or manifest_bytes + len(line) > 16 * 1024 ** 2):
                parts.append(archive_part(tree, work, label, len(parts) + 1, rows, source_bytes))
                rows, source_bytes, manifest_bytes = [], 0, 0
            rows.append(line)
            source_bytes += size
            manifest_bytes += len(line)
    if rows:
        parts.append(archive_part(tree, work, label, len(parts) + 1, rows, source_bytes))
    return parts


def archive_part(tree, work, label, number, rows, source_bytes):
    stem = f"{label}.part{number:06d}"
    manifest = work / (stem + ".manifest.jsonl")
    output = work / (stem + ".tar.zst")
    receipt_path = work / (stem + ".receipt.json")
    intended_digest = hashlib.sha256()
    for row in rows:
        intended_digest.update(row.encode("ascii"))
    intended = intended_digest.hexdigest()
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt["manifest_sha256"] != intended or sha(manifest) != intended or sha(output) != receipt["sha256"]:
            raise ValueError("completed archive prefix changed")
        return receipt
    # Incomplete derived outputs are retained under new names. Never overwrite
    # a prior complete part or touch the original filesystem during resumption.
    for path in (manifest, output):
        if path.exists() or path.is_symlink():
            if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_nlink != 1:
                raise ValueError("ambiguous incomplete archive artifact")
            path.rename(work / (path.name + ".incomplete-" + uuid.uuid4().hex))
    with manifest.open("x", encoding="ascii", newline="\n") as stream:
        stream.writelines(rows)
        stream.flush()
        os.fsync(stream.fileno())
    receipt = {"path": output.name, "manifest_path": manifest.name, "manifest_sha256": intended,
               "source_bytes": source_bytes, **compressed_tar(tree, manifest, output)}
    write(receipt_path, receipt)
    return receipt


def inventory_artifact(work, name, *, exclusions_only=False):
    path, marker = work / name, work / (name + ".receipt.json")
    if marker.exists():
        binding = json.loads(marker.read_text())
        if sha(path) != binding["sha256"]:
            raise ValueError("completed source inventory artifact changed")
        return binding
    if path.exists():
        path.rename(work / (path.name + ".incomplete-" + uuid.uuid4().hex))
    database = sqlite3.connect(work / "inventory.sqlite")
    with path.open("x", encoding="ascii") as stream:
        for tree, name, value in database.execute("SELECT tree,path,value FROM entries WHERE phase='final' ORDER BY tree,path"):
            entry = json.loads(value)
            if not exclusions_only or entry.get("external") or entry.get("volatile_socket"):
                stream.write(json.dumps({"tree": tree, "path": name, **entry}, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    database.close()
    binding = {"path": path.name, "sha256": sha(path), "bytes": path.stat().st_size}
    write(marker, binding)
    return binding


def archive(args):
    work, settings = workspace(args.workspace)
    frozen = json.loads((work / "frozen.json").read_text())
    if frozen["result"] != "FROZEN_PRIVATE_COPY":
        raise ValueError("final private capture required")
    accepted = json.loads((work / "quiescence-accepted.json").read_text())
    if accepted["result"] != "PASS" or accepted["frozen_sha256"] != sha(work / "frozen.json"):
        raise ValueError("root launcher postflight acceptance required")
    receipt = {"schema": SCHEMA, "result": "ARCHIVED", "capture": frozen, "settings": settings,
               "trees": {}, "boot_test": "NOT_TESTED"}
    for tree in ("root", "boot"):
        manifest = work / (tree + ".manifest.jsonl")
        manifest_receipt = work / (tree + ".manifest.receipt.json")
        if manifest_receipt.exists():
            binding = json.loads(manifest_receipt.read_text())
            if sha(manifest) != binding["sha256"]:
                raise ValueError("completed tree manifest changed")
        else:
            if manifest.exists():
                manifest.rename(work / (manifest.name + ".incomplete-" + uuid.uuid4().hex))
            binding = tree_manifest(work / "frozen" / tree, manifest)
            write(manifest_receipt, binding)
        receipt["trees"][tree] = {"manifest": binding,
                                 "archives": archive_parts(work / "frozen" / tree, manifest, work, tree)}
    receipt["external_restore_map"] = inventory_artifact(work, "external-restore-map.jsonl", exclusions_only=True)
    receipt["external_restore_map_sha256"] = receipt["external_restore_map"]["sha256"]
    receipt["source_observations"] = inventory_artifact(work, "source-observations.jsonl")
    receipt["raw_restore_required"] = frozen["external_files"] > 0
    if (work / "capture.json").exists():
        if json.loads((work / "capture.json").read_text()) != receipt:
            raise ValueError("completed capture receipt differs")
    else:
        write(work / "capture.json", receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("baseline", "prepare", "finalize", "archive"))
    parser.add_argument("--workspace", type=Path, required=True)
    for name in ("root", "boot", "layout", "catalog", "file-index", "catalog-sha256", "workspace-source-relative", "quiescence", "package-proof"):
        parser.add_argument("--" + name)
    args = parser.parse_args(argv)
    try:
        result = {"baseline": baseline, "prepare": prepare, "finalize": finalize, "archive": archive}[args.command](args)
        print(json.dumps(result or {"result": "PHASE_COMPLETED", "command": args.command}), flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, sqlite3.Error, subprocess.SubprocessError) as error:
        print(json.dumps({"result": "FAIL", "error": str(error)}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
