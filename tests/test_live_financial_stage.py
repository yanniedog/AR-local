"""Production storage fidelity must survive env precedence and actual-stage drift."""
from pathlib import Path
from types import SimpleNamespace
import json
import os

import pytest

import pi_live_financial_stage as stage


def fields(**extra):
    return {"User": "pi", "Environment": "AR_LOCAL_RAM_ROOT=/srv/capture",
            "EnvironmentFiles": "", "PassEnvironment": "", "UnsetEnvironment": "", **extra}


def resolve(value, reader=lambda *_: ([], {})):
    return stage.resolve_configuration(value, reader, lambda _: 1000)


def test_ordered_environment_files_override_unit_and_final_unset_restores_uid_default():
    def reader(path, optional):
        return ["/srv/first" if path.endswith("first") else "/srv/last"], {"path": path, "optional": optional}
    value = fields(EnvironmentFiles="/etc/first (ignore_errors=yes) /etc/last (ignore_errors=no)")
    actual = resolve(value, reader)
    assert actual["effective_root"] == "/srv/last"
    assert actual["environment_files"] == [{"path": "/etc/first", "optional": True}, {"path": "/etc/last", "optional": False}]
    assert resolve({**value, "UnsetEnvironment": "AR_LOCAL_RAM_ROOT=/srv/other"}, reader)["effective_root"] == "/srv/last"
    assert resolve({**value, "UnsetEnvironment": "AR_LOCAL_RAM_ROOT=/srv/last"}, reader)["effective_root"] == "/dev/shm/ar-local-1000"
    assert resolve({**value, "UnsetEnvironment": "AR_LOCAL_RAM_ROOT"}, reader)["effective_root"] == "/dev/shm/ar-local-1000"


@pytest.mark.parametrize("change", [
    {"PassEnvironment": "AR_LOCAL_RAM_ROOT"}, {"Environment": r"AR_LOCAL_RAM_ROOT=/srv/\x64isk"},
    {"EnvironmentFiles": "/etc/first (ignore_errors=yes) trailing"},
    {"Environment": "AR_LOCAL_RAM_ROOT=relative"}, {"Environment": "AR_LOCAL_RAM_ROOT=/srv/../other"},
    {"Environment": "AR_LOCAL_RAM_ROOT=/srv//other"}, {"Environment": "AR_LOCAL_RAM_ROOT=/srv/$OTHER"},
    {"User": ""},
])
def test_ambiguous_or_noncanonical_configuration_fails_closed(change):
    with pytest.raises(ValueError):
        resolve(fields(**change))


def test_quoted_literal_systemd_assignments_do_not_expand_or_publish_other_values():
    actual = stage.environment_file("#comment\nPASSWORD='private value'\nAR_LOCAL_RAM_ROOT='/srv/one'\nAR_LOCAL_RAM_ROOT=\"/srv/two\"\n")
    assert actual == ["/srv/one", "/srv/two"]
    result = resolve(fields(Environment='PASSWORD="private value" "AR_LOCAL_RAM_ROOT=/srv/two"'))
    assert result["effective_root"] == "/srv/two"
    assert "private" not in json.dumps(result) and "PASSWORD" not in json.dumps(result)


@pytest.mark.parametrize("text", ["AR_LOCAL_RAM_ROOT='/srv/one", "AR_LOCAL_RAM_ROOT=/srv/one\\\n/two", "OTHER=\"multi\nline\"", "export AR_LOCAL_RAM_ROOT=/srv/one"])
def test_unsupported_envfile_grammar_refuses_instead_of_guessing(text):
    with pytest.raises(ValueError):
        stage.environment_file(text)


def test_optional_missing_environment_file_is_distinct_from_required(monkeypatch):
    path = Path("/etc/missing.env")
    monkeypatch.setattr(stage, "canonical", lambda _: path)
    def lstat(self):
        if self == path:
            raise FileNotFoundError()
        return SimpleNamespace(st_mode=0o40755, st_uid=0)
    monkeypatch.setattr(Path, "lstat", lstat)
    assert stage.read_environment_file(str(path), True) == ([], {"path": str(path), "optional": True, "missing": True})
    with pytest.raises(ValueError, match="required"):
        stage.read_environment_file(str(path), False)


DISK = {"st_dev": 5, "fstype": "ext4", "mount": "/", "fsroot": "/", "major_minor": "1:2"}
RAM = {"st_dev": 9, "fstype": "tmpfs", "mount": "/dev/shm", "fsroot": "/", "major_minor": "0:9"}


def probe(path):
    return RAM if path.as_posix().startswith("/dev/shm") else DISK


def test_default_disk_profile_uses_new_isolated_operation_on_same_filesystem(tmp_path):
    binding = stage.choose_stage(tmp_path / "op", "production", {"effective_root": "/srv/capture"}, probe)
    assert binding["root"] == str(tmp_path / "op/capture-stage")
    assert binding["production_fidelity"] is True and binding["qualification"] == "PRODUCTION_STORAGE"
    actual = stage.verify_stage({"ram_staged": True, "ram_root": binding["root"]}, binding, probe)
    assert actual["filesystem"] == DISK
    with pytest.raises(ValueError, match="different staging"):
        stage.verify_stage({"ram_staged": True, "ram_root": str(tmp_path / "data/runs-archive/.daily-raw-stage")}, binding, probe)
    with pytest.raises(ValueError, match="filesystem changed"):
        stage.verify_stage({"ram_staged": True, "ram_root": binding["root"]}, binding, lambda _: RAM)


def test_tmpfs_profile_is_supplemental_for_configured_disk_and_cannot_claim_fidelity(tmp_path):
    binding = stage.choose_stage(tmp_path / "op", "tmpfs-supplemental", {"effective_root": "/srv/capture"}, probe)
    assert binding["production_fidelity"] is False and binding["qualification"] == "SUPPLEMENTAL"
    assert binding["filesystem"] == RAM and binding["production_filesystem"] == DISK


def test_production_tmpfs_requires_same_mount_and_device(tmp_path):
    result = stage.choose_stage(tmp_path / "op", "production", {"effective_root": "/dev/shm/configured"}, probe)
    assert result["production_fidelity"] and result["filesystem"] == RAM
    with pytest.raises(ValueError, match="does not match"):
        stage.choose_stage(tmp_path / "op", "production", {"effective_root": "/srv/other"},
            lambda p: {**DISK, "st_dev": 6} if p.as_posix() == "/srv/other" else DISK)


def test_existing_stage_is_never_reused(tmp_path):
    (tmp_path / "op/capture-stage").mkdir(parents=True)
    with pytest.raises(ValueError, match="already exists"):
        stage.choose_stage(tmp_path / "op", "production", {"effective_root": "/srv/capture"}, probe)


def test_bind_mount_namespace_changes_context_but_not_backing_identity(tmp_path):
    binding = stage.choose_stage(tmp_path / "op", "production", {"effective_root": "/srv/capture"}, probe)
    sandbox = {**DISK, "mount": binding["root"], "fsroot": "/srv/ar-local/canary/op/capture-stage"}
    actual = stage.verify_stage({"ram_staged": True, "ram_root": binding["root"]}, binding, lambda _: sandbox)
    assert actual["filesystem"] == sandbox and actual["production_fidelity"] is True


def test_worker_checks_created_directory_identity_before_capture(monkeypatch):
    binding = {"root": "/srv/op/capture-stage", "directory_identity": {"st_dev": 5, "st_ino": 7}, "filesystem": DISK}
    monkeypatch.setattr(stage, "directory_identity", lambda _: {"st_dev": 5, "st_ino": 8})
    with pytest.raises(ValueError, match="directory identity"):
        stage.verify_directory(binding)
    monkeypatch.setattr(stage, "directory_identity", lambda _: binding["directory_identity"])
    monkeypatch.setattr(stage, "filesystem", lambda _: {**DISK, "mount": binding["root"], "fsroot": "/srv/op/capture-stage"})
    assert stage.verify_directory(binding)["mount"] == binding["root"]


def test_truncated_duplicate_or_extra_systemctl_properties_are_refused():
    text = "\n".join(f"{k}={v}" for k, v in fields().items())
    assert stage.property_fields(text) == fields()
    for invalid in (text.rsplit("\n", 1)[0], text + "\nUser=pi", text + "\nUnexpected=x"):
        with pytest.raises(ValueError):
            stage.property_fields(invalid)
    with pytest.raises(ValueError, match="complete exact"):
        resolve({"User": "pi"})


def test_repeated_environment_file_properties_preserve_all_files_and_duplicate_order():
    text = "User=pi\nEnvironment=\nPassEnvironment=\nUnsetEnvironment=\n" + "\n".join([
        "EnvironmentFiles=/etc/private.env (ignore_errors=yes)",
        "EnvironmentFiles=/etc/public.env (ignore_errors=no)",
        "EnvironmentFiles=/etc/private.env (ignore_errors=yes)"])
    seen = []
    def reader(name, optional):
        seen.append((name, optional))
        return ["/srv/" + str(len(seen))], {"path": name}
    result = resolve(stage.property_fields(text), reader)
    assert result["effective_root"] == "/srv/3"
    assert seen == [("/etc/private.env", True), ("/etc/public.env", False), ("/etc/private.env", True)]


def root_reader_namespace():
    from pi_live_financial_stage_env import ROOT_READER
    namespace = {"__name__": "offline_root_reader_test"}
    exec(compile(ROOT_READER, "<fixed-root-reader>", "exec"), namespace)
    return namespace


def test_root_literal_emits_only_allowlisted_assignments_and_retains_file_order(monkeypatch):
    namespace = root_reader_namespace()
    monkeypatch.setitem(namespace, "canonical", lambda value: stage.canonical_name(value))
    assert namespace["assignments"]("IGNORED=example\nAR_LOCAL_RAM_ROOT='/srv/capture'\n") == ["/srv/capture"]
    for text in ("OTHER=one\\\ntwo", "OTHER='multiline", "export OTHER=x"):
        with pytest.raises(ValueError):
            namespace["assignments"](text)
    output = "EnvironmentFiles=/etc/one (ignore_errors=yes)\nEnvironmentFiles=/etc/two (ignore_errors=no)\nEnvironmentFiles=/etc/one (ignore_errors=yes)\n"
    monkeypatch.setattr(namespace["subprocess"], "run", lambda *a, **k: SimpleNamespace(stdout=output))
    monkeypatch.setitem(namespace, "read_file", lambda path, optional: {"path": path, "optional": optional})
    assert namespace["collect"]()["files"] == [
        {"path": "/etc/one", "optional": True}, {"path": "/etc/two", "optional": False}, {"path": "/etc/one", "optional": True}]


def test_root_literal_limits_property_bytes_and_file_count_before_read(monkeypatch):
    namespace = root_reader_namespace()
    seen = []
    monkeypatch.setitem(namespace, "read_file", lambda *args: seen.append(args) or {})
    monkeypatch.setattr(namespace["subprocess"], "run", lambda *a, **k: SimpleNamespace(stdout='x' * 65537))
    with pytest.raises(ValueError, match="property bound"):
        namespace["collect"]()
    assert seen == []
    output = "EnvironmentFiles=/etc/one (ignore_errors=yes)\n" * 33
    monkeypatch.setattr(namespace["subprocess"], "run", lambda *a, **k: SimpleNamespace(stdout=output))
    with pytest.raises(ValueError, match="file count bound"):
        namespace["collect"]()
    assert len(seen) == 32


@pytest.mark.parametrize('separator', ['\u2028', '\u0085', '\u00a0', '\u001c', '\v', '\f', '\0', '\r'])
def test_non_systemd_separators_never_create_phantom_staging_assignment(separator):
    text = 'OTHER=opaque' + separator + 'AR_LOCAL_RAM_ROOT=/srv/wrong'
    for reader in (stage.environment_file, root_reader_namespace()['assignments']):
        with pytest.raises(ValueError, match='separator'):
            reader(text)


@pytest.mark.skipif(os.name != "posix", reason="root NOFOLLOW descriptor contract is POSIX")
def test_root_literal_projects_mode0600_file_without_returning_unrelated_values(tmp_path, monkeypatch):
    namespace = root_reader_namespace()
    path = tmp_path / "private.env"
    path.write_text("OTHER=example\nAR_LOCAL_RAM_ROOT=/srv/capture\n")
    path.chmod(0o600)
    real_lstat, real_fstat = Path.lstat, os.fstat
    def root_stat(value, directory=False):
        return SimpleNamespace(**{name: (0 if name == 'st_uid' else 0o40755 if name == 'st_mode' and directory else getattr(value, name))
            for name in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')})
    monkeypatch.setitem(namespace, "canonical", lambda name: Path(name))
    monkeypatch.setattr(Path, "lstat", lambda self: root_stat(real_lstat(self), self != path))
    monkeypatch.setattr(os, "fstat", lambda fd: root_stat(real_fstat(fd)))
    result = namespace["read_file"](str(path), False)
    assert result['assignments'] == ['/srv/capture'] and result['identity'][2] & 0o777 == 0o600
    assert 'example' not in json.dumps(result) and 'OTHER' not in json.dumps(result)
