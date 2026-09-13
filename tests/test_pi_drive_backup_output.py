"""Restic transport fixtures only; no source data or backup acceptance mocks."""
import io
import json
import subprocess
import sys
import tempfile

import pytest

import pi_drive_backup as backup
import pi_drive_backup_output as output

SUMMARY = {"message_type": "summary", "snapshot_id": "a" * 64, "data_added_packed": 123}
RAW_SUMMARY = json.dumps(SUMMARY).encode() + b"\n"


def read(raw):
    return output.command_output(io.BytesIO(raw), ("backup", "--json"), guard=lambda: None)


def test_more_than_sixteen_mib_progress_returns_only_exact_final_summary():
    with tempfile.TemporaryFile() as stream:
        record = json.dumps({"message_type": "status", "current_files": ["private-transport-path" * 200]}).encode() + b"\n"
        for _ in range(5000):
            stream.write(record)
        assert stream.tell() > output.MAX_OUTPUT_BYTES
        stream.write(RAW_SUMMARY)
        result = output.command_output(stream, ("backup", "--json"), guard=lambda: None)
    assert result == RAW_SUMMARY.decode() and "private-transport-path" not in result
    assert backup._summary(result) == SUMMARY


@pytest.mark.parametrize("raw", [b"", b'{"message_type":"status"}\n', RAW_SUMMARY * 2,
    RAW_SUMMARY + b'{"message_type":"status"}\n', b'{"message_type":"summary"}\n',
    json.dumps({**SUMMARY, "snapshot_id": "not-an-id"}).encode(),
    json.dumps({**SUMMARY, "dry_run": True}).encode(), b'[]\n', b'null\n',
    b'{"private":"do-not-expose"', b'\xff\n', b'{"message_type":"status","n":NaN}\n'])
def test_missing_duplicate_invalid_nonfinal_or_dry_summary_fails_closed(raw):
    with pytest.raises(RuntimeError) as failed:
        read(raw)
    assert "do-not-expose" not in str(failed.value)


def test_eof_summary_whitespace_and_future_progress_message_are_supported():
    raw = b'\n{"message_type":"future_progress","private":"not-retained"}\n' + RAW_SUMMARY.rstrip(b"\n")
    assert read(raw) == RAW_SUMMARY.decode().rstrip("\n")


def test_line_limit_rejects_record_without_allocating_whole_stream():
    class Bound(io.BytesIO):
        def readline(self, size=-1):
            assert size == output.MAX_BACKUP_RECORD_BYTES + 1
            return super().readline(size)
        def read(self, *_):
            pytest.fail("backup stream must never use whole-output read")
    with pytest.raises(RuntimeError, match="JSON record exceeded"):
        output.command_output(Bound(b"x" * (output.MAX_BACKUP_RECORD_BYTES + 2)), ("backup", "--json"), guard=lambda: None)


def test_guard_and_processing_deadline_remain_fatal(monkeypatch):
    def stopped():
        raise backup.Blocked("quiet-window fixture")
    with pytest.raises(backup.Blocked, match="quiet-window fixture"):
        output.command_output(io.BytesIO(RAW_SUMMARY), ("backup", "--json"), guard=stopped)
    ticks = iter([0, 61])
    monkeypatch.setattr(output.time, "monotonic", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="processing deadline"):
        read(RAW_SUMMARY)


@pytest.mark.parametrize("arguments", [("stats", "--json"), ("check",), ("backup",)])
def test_other_command_output_keeps_original_sixteen_mib_limit(arguments):
    assert output.command_output(io.BytesIO(b"unchanged\n"), arguments, guard=lambda: None) == "unchanged\n"
    with tempfile.TemporaryFile() as stream:
        stream.truncate(output.MAX_OUTPUT_BYTES + 1)
        with pytest.raises(RuntimeError, match="command output exceeded"):
            output.command_output(stream, arguments, guard=lambda: None)


@pytest.mark.parametrize("exit_code", [0, 1, 11])
def test_real_child_large_progress_preserves_exit_and_private_diagnostic_semantics(tmp_path, monkeypatch, exit_code):
    config = backup.Config(tmp_path, tmp_path, "unused", tmp_path/"password", tmp_path/"config", [])
    original = subprocess.Popen
    code = ("import json,sys;record=json.dumps({'message_type':'status','current_files':['private'*1000]})+'\\n';"
            "[sys.stdout.buffer.write(record.encode()) for _ in range(3000)];"
            f"sys.stdout.buffer.write({RAW_SUMMARY!r});sys.exit({exit_code})")
    monkeypatch.setattr(backup.subprocess, "Popen", lambda _args, **kwargs: original([sys.executable,"-c",code], **kwargs))
    monkeypatch.setattr(backup, "guard_window", lambda: None)
    if exit_code == 0:
        assert backup.Restic(config).run("backup", "--json") == RAW_SUMMARY.decode()
    else:
        kind = backup.Blocked if exit_code == 11 else RuntimeError
        with pytest.raises(kind):
            backup.Restic(config).run("backup", "--json")
    result = json.loads(next((tmp_path/"diagnostics").glob("*/result.json")).read_text())
    assert result["exit_code"] == exit_code and result["reader_complete"]
    assert not (tmp_path/"latest-verified.json").exists()
