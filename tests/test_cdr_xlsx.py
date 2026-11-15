from __future__ import annotations

import tracemalloc
from contextlib import closing
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import openpyxl
import pytest
import cdr_xlsx

from cdr_xlsx import write_workbook


class GeneratedRows:
    def __init__(self, count: int, value_size: int) -> None:
        self.count = count
        self.value = "x" * value_size

    def __len__(self) -> int:
        return self.count

    def __iter__(self):
        for index in range(self.count):
            yield {"index": index, "value": self.value}


def test_write_workbook_streams_rows_without_materializing_sheet_xml(tmp_path: Path) -> None:
    output = tmp_path / "streamed.xlsx"
    rows = GeneratedRows(count=8_000, value_size=1_000)

    tracemalloc.start()
    write_workbook(output, {"generated": rows})
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert peak < 4_000_000
    workbook = openpyxl.load_workbook(output, read_only=True)
    sheet = workbook["generated"]
    assert sum(1 for _ in sheet.iter_rows()) == 8_001
    assert sheet["A2"].value == 0
    assert sheet["B8001"].value == "x" * 1_000


def test_write_workbook_preserves_empty_sheet(tmp_path: Path) -> None:
    output = tmp_path / "empty.xlsx"
    write_workbook(output, {"empty": []})

    workbook = openpyxl.load_workbook(output, read_only=True)
    assert workbook["empty"]["A1"].value == "empty"


@pytest.mark.parametrize("count", [0, 1, 3, 4, 6, 7])
def test_partition_preserves_all_rows_headers_and_sheet_limits(tmp_path, monkeypatch, count):
    assert cdr_xlsx.MAX_WORKSHEET_ROWS == 1_048_576
    monkeypatch.setattr(cdr_xlsx, "MAX_WORKSHEET_ROWS", 4)
    rows = [{"id": f"000{index}", **({"late": "last"} if index == count - 1 else {})}
            for index in range(count)]
    output = tmp_path / "partitioned.xlsx"
    write_workbook(output, {"facts": rows})
    with closing(openpyxl.load_workbook(output, read_only=True)) as workbook:
        actual = []
        assert len(workbook.sheetnames) == max(1, (count + 2) // 3)
        for sheet in workbook:
            values = list(sheet.values)
            assert len(values) <= 4
            if count:
                assert values[0] == ("id", "late")
                actual.extend(values[1:])
            else:
                assert values == [("empty",)]
        assert [row[0] for row in actual] == [row["id"] for row in rows]
        assert [row[1] for row in actual] == [row.get("late", "") for row in rows]
    with zipfile.ZipFile(output) as archive:
        for name in archive.namelist():
            if name.startswith("xl/worksheets/"):
                xml = ET.fromstring(archive.read(name))
                ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                data = xml.findall("s:sheetData/s:row", ns)
                assert len(data) <= 4
                assert [int(row.attrib["r"]) for row in data] == list(range(1, len(data) + 1))
                if count:
                    assert xml.find("s:autoFilter", ns).attrib["ref"] == f"A1:B{len(data)}"


def test_partitioned_names_are_unique_valid_and_keep_all_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(cdr_xlsx, "MAX_WORKSHEET_ROWS", 3)
    output = tmp_path / "names.xlsx"
    names = ["facts", "FACTS_2", "a" * 40, "a" * 31 + ":"]
    write_workbook(output, {name: [{"table": index}] * 3 for index, name in enumerate(names)})
    with closing(openpyxl.load_workbook(output, read_only=True)) as workbook:
        assert len(workbook.sheetnames) == 8
        assert len({name.lower() for name in workbook.sheetnames}) == 8
        assert all(len(name) <= 31 and not cdr_xlsx.INVALID_SHEET_CHARS.search(name)
                   for name in workbook.sheetnames)
        assert [row[0] for sheet in workbook for row in list(sheet.values)[1:]] == [
            index for index in range(4) for _ in range(3)]


def test_partition_keeps_streaming_memory_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(cdr_xlsx, "MAX_WORKSHEET_ROWS", 3_001)
    rows = GeneratedRows(count=8_000, value_size=1_000)
    tracemalloc.start()
    try:
        write_workbook(tmp_path / "bounded.xlsx", {"facts": rows})
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4_000_000


@pytest.mark.parametrize('existing', [True, False])
def test_replay_budget_failure_during_sheet_write_never_replaces_workbook(tmp_path, existing):
    from dataclasses import replace
    from cdr_product_changes import _product_key, _fact_key
    from cdr_replay_rows import ReplayStore, ReplayLimits, ReplayLimitError, encoded
    values = [dict(provider='Technical', product_id='control', dataset='Savings', fact_id=str(i), text='x'*100) for i in range(3)]
    first_pass = sum(len(encoded(value)) for value in values)
    target = tmp_path / 'facts.xlsx'
    if existing: write_workbook(target, {'original': [{'kept': 'original bytes'}]})
    original = target.read_bytes() if existing else None
    limits = replace(ReplayLimits(), read_bytes=first_pass + len(encoded(values[0])))
    with pytest.raises(ReplayLimitError, match='read/row budget'):
        with ReplayStore(tmp_path, key_of=_product_key, validate_fact=_fact_key, limits=limits) as spool:
            spool.facts.extend(values); spool.facts.seal()
            write_workbook(target, {'facts': spool.facts})
    assert (target.read_bytes() if target.exists() else None) == original
    assert not list(tmp_path.glob('.facts.xlsx.tmp-*'))


def test_workbook_replaces_only_complete_archive_and_preserves_mode(tmp_path, monkeypatch):
    import os
    import stat
    target = tmp_path / 'facts.xlsx'; target.write_bytes(b'original'); target.chmod(0o600)
    original_mode = stat.S_IMODE(target.stat().st_mode)
    replace = cdr_xlsx.os.replace; observed = []
    def checked(source, destination):
        assert target.read_bytes() == b'original'
        with zipfile.ZipFile(source) as archive: assert archive.testzip() is None
        observed.append(source); replace(source, destination)
    monkeypatch.setattr(cdr_xlsx.os, 'replace', checked)
    write_workbook(target, {'complete': [{'value': 1}]})
    assert len(observed) == 1 and not observed[0].exists()
    assert stat.S_IMODE(target.stat().st_mode) == original_mode


@pytest.mark.skipif(cdr_xlsx.os.name != 'posix', reason='actual POSIX directory fsync')
def test_replaced_workbook_parent_is_fsynced_after_atomic_replace(tmp_path, monkeypatch):
    import os
    import stat
    target = tmp_path / 'durable.xlsx'
    sync = cdr_xlsx.os.fsync; replace = cdr_xlsx.os.replace; events = []
    def record_sync(descriptor):
        events.append('directory_sync' if stat.S_ISDIR(os.fstat(descriptor).st_mode) else 'file_sync')
        sync(descriptor)
    def record_replace(source, destination):
        replace(source, destination); events.append('replace')
    monkeypatch.setattr(cdr_xlsx.os, 'fsync', record_sync)
    monkeypatch.setattr(cdr_xlsx.os, 'replace', record_replace)
    write_workbook(target, {'complete': [{'value': 1}]})
    assert events == ['file_sync', 'replace', 'directory_sync']
