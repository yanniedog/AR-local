"""Official RBA cash-rate decision ingestion for mobile payload publication."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Callable, Iterable, Optional
from urllib.request import Request, urlopen

SOURCE_URL = "https://www.rba.gov.au/statistics/cash-rate/"
PUBLICATION_GRACE = timedelta(hours=6)


class RbaOfficialError(RuntimeError):
    """The official decision table was unavailable or failed validation."""


class _CashRateTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.cells: list[str] = []
        self.cell_parts: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        if tag == "table" and attributes.get("id") == "datatable":
            self.in_table = True
        elif self.in_table and tag == "tr":
            self.in_row = True
            self.cells = []
        elif self.in_row and tag in ("th", "td"):
            self.in_cell = True
            self.cell_parts = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.in_cell and tag in ("th", "td"):
            self.cells.append(" ".join("".join(self.cell_parts).split()))
            self.in_cell = False
        elif self.in_row and tag == "tr":
            if self.cells:
                self.rows.append(self.cells)
            self.in_row = False
        elif self.in_table and tag == "table":
            self.in_table = False


def parse_cash_rate_table(html: str) -> list[dict]:
    parser = _CashRateTableParser()
    parser.feed(html)
    records: list[dict] = []
    for cells in parser.rows:
        if len(cells) < 3:
            continue
        try:
            effective = datetime.strptime(cells[0], "%d %b %Y").date()
            change = Decimal(cells[1].replace("+", ""))
            target = Decimal(cells[2])
        except (ValueError, InvalidOperation):
            continue
        change_bps = int(change * 100)
        rate_bps = int(target * 100)
        if Decimal(change_bps) / 100 != change or Decimal(rate_bps) / 100 != target:
            raise RbaOfficialError(f"non-integral basis-point row for {effective.isoformat()}")
        records.append({
            "effective": effective,
            "change_bps": change_bps,
            "rate_bps": rate_bps,
        })
    if not records:
        raise RbaOfficialError("official cash-rate table contained no usable rows")
    return records


def fetch_cash_rate_table(timeout: int = 20) -> str:
    request = Request(
        SOURCE_URL,
        headers={"User-Agent": "AustralianRates/1.0 (+https://github.com/yanniedog/AR-local)"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS authority
            return response.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - normalized at the source boundary
        raise RbaOfficialError(f"official RBA table fetch failed: {exc}") from exc


def decision_entries(records: Iterable[dict]) -> list[dict]:
    entries: list[dict] = []
    for record in records:
        effective = record["effective"]
        if effective < date(2025, 2, 19):
            continue
        delta_bps = int(record["change_bps"])
        rate_bps = int(record["rate_bps"])
        announcement = effective - timedelta(days=1)
        entries.append({
            "date": announcement.isoformat(),
            "effective": effective.isoformat() if delta_bps else None,
            "rate": rate_bps / 100,
            "delta_bps": delta_bps,
            "outcome": "hike" if delta_bps > 0 else "cut" if delta_bps < 0 else "hold",
        })
    return sorted(entries, key=lambda item: item["date"])


def merge_calendar(
    calendar: dict,
    records: Iterable[dict],
    *,
    now: Optional[datetime] = None,
) -> dict:
    decisions_by_date = {item["date"]: dict(item) for item in calendar.get("decisions", [])}
    for item in decision_entries(records):
        decisions_by_date[item["date"]] = item
    decisions = sorted(decisions_by_date.values(), key=lambda item: item["date"])
    for previous, current in zip(decisions, decisions[1:]):
        expected_bps = round(float(previous["rate"]) * 100) + int(current["delta_bps"])
        actual_bps = round(float(current["rate"]) * 100)
        if actual_bps != expected_bps:
            raise RbaOfficialError(
                f"cash-rate continuity failed at {current['date']}: "
                f"expected {expected_bps}bps, received {actual_bps}bps"
            )
    recorded = set(decisions_by_date)
    schedule = [item for item in calendar.get("schedule", []) if item.get("date") not in recorded]

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now.astimezone(timezone.utc) - PUBLICATION_GRACE
    unresolved = []
    for meeting in schedule:
        try:
            announced = datetime.fromisoformat(str(meeting["announce_utc"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            raise RbaOfficialError(f"invalid scheduled meeting: {meeting!r}") from None
        if announced <= cutoff:
            unresolved.append(str(meeting.get("date") or "unknown"))
    if unresolved:
        raise RbaOfficialError(
            "official RBA decision missing for elapsed meeting(s): " + ", ".join(unresolved)
        )
    return {
        "timezone": calendar.get("timezone") or "Australia/Sydney",
        "decisions": decisions,
        "schedule": schedule,
    }


def load_calendar(
    calendar: dict,
    *,
    fetch: Callable[[], str] = fetch_cash_rate_table,
    now: Optional[datetime] = None,
) -> dict:
    return merge_calendar(calendar, parse_cash_rate_table(fetch()), now=now)
