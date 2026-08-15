"""Small stdlib XLSX writer for local CDR exports."""

from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
LEADING_ZERO_ID = re.compile(r"^[+-]?0\d")
DECIMAL_NUMBER = re.compile(r"^[+-]?0\.")


def cell_ref(row: int, col: int) -> str:
    letters = ""
    n = col
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row}"


def sheet_name(name: str, used: set[str]) -> str:
    base = INVALID_SHEET_CHARS.sub("_", name).strip()[:31] or "Sheet"
    candidate = base
    i = 2
    while candidate.lower() in used:
        suffix = f"_{i}"
        candidate = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(candidate.lower())
    return candidate


def to_rows(rows: Sequence[Mapping[str, Any]]) -> List[List[Any]]:
    if not rows:
        return []
    keys: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in keys:
                keys.append(str(key))
    return [keys] + [[row.get(key, "") for key in keys] for row in rows]


def is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        float(value)
        stripped = value.strip()
        if LEADING_ZERO_ID.match(stripped) and not DECIMAL_NUMBER.match(stripped):
            return False
        return True
    except ValueError:
        return False


def cell_xml(row: int, col: int, value: Any) -> str:
    ref = cell_ref(row, col)
    if value is None:
        return f'<c r="{ref}"/>'
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'
    if is_number(value):
        return f'<c r="{ref}"><v>{html.escape(str(value))}</v></c>'
    safe = html.escape(str(value), quote=False)
    return f'<c r="{ref}" t="inlineStr"><is><t>{safe}</t></is></c>'


def rows_xml(rows: Sequence[Sequence[Any]]) -> str:
    out = []
    for r_idx, row in enumerate(rows, 1):
        cells = "".join(cell_xml(r_idx, c_idx, value) for c_idx, value in enumerate(row, 1))
        out.append(f'<row r="{r_idx}">{cells}</row>')
    return "".join(out)


def sheet_xml(rows: Sequence[Sequence[Any]]) -> str:
    max_col = max((len(r) for r in rows), default=1)
    max_row = max(len(rows), 1)
    ref = f"A1:{cell_ref(max_row, max_col)}"
    widths = "".join(f'<col min="{i}" max="{i}" width="18" customWidth="1"/>' for i in range(1, max_col + 1))
    filters = f'<autoFilter ref="{ref}"/>' if rows and len(rows) > 1 else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{widths}</cols><sheetData>{rows_xml(rows)}</sheetData>{filters}</worksheet>"
    )


def _sheet_columns(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    columns: List[str] = []
    seen: set[str] = set()
    for row in rows:
        for raw_key in row.keys():
            key = str(raw_key)
            if key not in seen:
                columns.append(key)
                seen.add(key)
    return columns


def _write_xml_part(handle: Any, value: str) -> None:
    handle.write(value.encode("utf-8"))


def _write_sheet(
    archive: zipfile.ZipFile,
    path: str,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    columns = _sheet_columns(rows)
    row_count = len(rows) + 1 if rows else 1
    column_count = max(len(columns), 1)
    ref = f"A1:{cell_ref(row_count, column_count)}"
    widths = "".join(
        f'<col min="{idx}" max="{idx}" width="18" customWidth="1"/>'
        for idx in range(1, column_count + 1)
    )
    filters = f'<autoFilter ref="{ref}"/>' if rows else ""
    prefix = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{widths}</cols><sheetData>"
    )
    with archive.open(path, "w", force_zip64=True) as handle:
        _write_xml_part(handle, prefix)
        if not rows:
            _write_xml_part(handle, '<row r="1"><c r="A1" t="inlineStr"><is><t>empty</t></is></c></row>')
        else:
            header = "".join(cell_xml(1, idx, value) for idx, value in enumerate(columns, 1))
            _write_xml_part(handle, f'<row r="1">{header}</row>')
            for row_index, row in enumerate(rows, 2):
                cells = "".join(
                    cell_xml(row_index, column_index, row.get(column, ""))
                    for column_index, column in enumerate(columns, 1)
                )
                _write_xml_part(handle, f'<row r="{row_index}">{cells}</row>')
        _write_xml_part(handle, f"</sheetData>{filters}</worksheet>")


def workbook_xml(names: Sequence[str]) -> str:
    sheets = "".join(
        f'<sheet name="{html.escape(name)}" sheetId="{idx}" r:id="rId{idx}"/>'
        for idx, name in enumerate(names, 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets></workbook>"
    )


def rels_xml(names: Sequence[str]) -> str:
    worksheet_rels = "".join(
        f'<Relationship Id="rId{idx}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{idx}.xml"/>'
        for idx, _ in enumerate(names, 1)
    )
    styles_id = len(names) + 1
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{worksheet_rels}"
        f'<Relationship Id="rId{styles_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/></Relationships>'
    )


def content_types_xml(sheet_count: int) -> str:
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{idx}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for idx in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{overrides}</Types>"
    )


def root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )


def styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Aptos"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellXfs>'
        '</styleSheet>'
    )


def write_workbook(path: Path, sheets: Mapping[str, Sequence[Mapping[str, Any]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    named_sheets = [(sheet_name(raw_name, used), rows) for raw_name, rows in sheets.items()]
    names = [name for name, _ in named_sheets]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml(len(names)))
        zf.writestr("_rels/.rels", root_rels_xml())
        zf.writestr("xl/workbook.xml", workbook_xml(names))
        zf.writestr("xl/_rels/workbook.xml.rels", rels_xml(names))
        zf.writestr("xl/styles.xml", styles_xml())
        for idx, (_, rows) in enumerate(named_sheets, 1):
            _write_sheet(zf, f"xl/worksheets/sheet{idx}.xml", rows)
