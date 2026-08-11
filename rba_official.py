"""Official RBA cash-rate decision ingestion for mobile payload publication."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import re
from typing import Callable, Iterable, Optional
from urllib.request import Request, urlopen

SOURCE_URL = "https://www.rba.gov.au/statistics/cash-rate/"
MEDIA_RELEASE_FEED_URL = "https://www.rba.gov.au/rss/rss-cb-media-releases.xml"
OVERVIEW_URL = "https://www.rba.gov.au/cash-rate-target-overview.html"
PUBLICATION_GRACE = timedelta(0)


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
    """Parse exact-basis-point decision rows from the official RBA HTML table."""
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


def _fetch_url(url: str, timeout: int = 20) -> str:
    request = Request(
        url,
        headers={"User-Agent": "AustralianRates/1.0 (+https://github.com/yanniedog/AR-local)"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS authority
            return response.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - normalized at the source boundary
        raise RbaOfficialError(f"official RBA fetch failed for {url}: {exc}") from exc


def fetch_cash_rate_table(timeout: int = 20) -> str:
    """Fetch the official historical cash-rate table."""
    return _fetch_url(SOURCE_URL, timeout)


def fetch_media_release_feed(timeout: int = 20) -> str:
    """Fetch the RBA media-release RSS feed published at the decision instant."""
    return _fetch_url(MEDIA_RELEASE_FEED_URL, timeout)


def fetch_cash_rate_overview(timeout: int = 20) -> str:
    """Fetch the live official cash-rate overview fallback."""
    return _fetch_url(OVERVIEW_URL, timeout)


def parse_media_release_feed(xml: str, calendar: dict) -> Optional[dict]:
    """Extract the newest monetary-policy decision from the official RSS item."""
    candidates: list[tuple[str, str]] = []
    for item_match in re.finditer(r"<item\b[\s\S]*?</item>", xml, flags=re.IGNORECASE):
        item = item_match.group(0)
        if not re.search(r"Monetary Policy Decision", item, re.I):
            continue
        date_match = re.search(r"<dc:date>(\d{4}-\d{2}-\d{2})T", item, re.I)
        rate_match = re.search(
            r"cash rate target[^.]*?\b(?:at|to)\s+(\d+(?:\.\d+)?)\s+per cent",
            item,
            re.I,
        )
        if not date_match or not rate_match:
            continue
        candidates.append((date_match.group(1), rate_match.group(1)))
    if not candidates:
        return None
    announcement_text, rate_text = max(candidates, key=lambda candidate: candidate[0])
    announcement = date.fromisoformat(announcement_text)
    prior = sorted(
        (
            decision
            for decision in calendar.get("decisions", [])
            if decision.get("date", "") < announcement.isoformat()
        ),
        key=lambda decision: decision["date"],
    )
    if not prior:
        return None
    rate_bps = int(Decimal(rate_text) * 100)
    previous_bps = int(Decimal(str(prior[-1]["rate"])) * 100)
    delta_bps = rate_bps - previous_bps
    return {
        "date": announcement.isoformat(),
        "effective": (announcement + timedelta(days=1)).isoformat() if delta_bps else None,
        "rate": rate_bps / 100,
        "delta_bps": delta_bps,
        "outcome": "hike" if delta_bps > 0 else "cut" if delta_bps < 0 else "hold",
    }


def parse_cash_rate_overview(html: str, calendar: dict) -> Optional[dict]:
    """Extract the live target/effective date when the RSS item is unavailable."""
    text = " ".join(re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ").split())
    rate_match = re.search(r"Cash rate target\s+(\d+(?:\.\d+)?)\s*%", text, re.I)
    effective_match = re.search(
        r"Effective date\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text, re.I
    )
    if not rate_match or not effective_match:
        return None
    try:
        effective = datetime.strptime(" ".join(effective_match.groups()), "%d %B %Y").date()
    except ValueError:
        return None
    announcement = effective - timedelta(days=1)
    prior = sorted(
        (
            decision
            for decision in calendar.get("decisions", [])
            if decision.get("date", "") < announcement.isoformat()
        ),
        key=lambda decision: decision["date"],
    )
    if not prior:
        return None
    rate_bps = int(Decimal(rate_match.group(1)) * 100)
    previous_bps = int(Decimal(str(prior[-1]["rate"])) * 100)
    delta_bps = rate_bps - previous_bps
    return {
        "date": announcement.isoformat(),
        "effective": effective.isoformat() if delta_bps else None,
        "rate": rate_bps / 100,
        "delta_bps": delta_bps,
        "outcome": "hike" if delta_bps > 0 else "cut" if delta_bps < 0 else "hold",
    }


def decision_entries(records: Iterable[dict]) -> list[dict]:
    """Map effective-dated official rows to announcement-dated app decisions."""
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
    extra_decisions: Iterable[dict] = (),
) -> dict:
    """Merge verified official rows and reject inconsistent or overdue gaps."""
    decisions_by_date = {item["date"]: dict(item) for item in calendar.get("decisions", [])}
    for item in decision_entries(records):
        decisions_by_date[item["date"]] = item
    for item in sorted(extra_decisions, key=lambda decision: decision["date"]):
        previous = sorted(
            (
                decision
                for decision in decisions_by_date.values()
                if decision["date"] < item["date"]
            ),
            key=lambda decision: decision["date"],
        )
        normalized = dict(item)
        if previous:
            previous_bps = int(Decimal(str(previous[-1]["rate"])) * 100)
            current_bps = int(Decimal(str(normalized["rate"])) * 100)
            delta_bps = current_bps - previous_bps
            normalized["delta_bps"] = delta_bps
            normalized["outcome"] = (
                "hike" if delta_bps > 0 else "cut" if delta_bps < 0 else "hold"
            )
            if delta_bps == 0:
                normalized["effective"] = None
        decisions_by_date[normalized["date"]] = normalized
    decisions = sorted(decisions_by_date.values(), key=lambda item: item["date"])
    for previous, current in zip(decisions, decisions[1:]):
        expected_bps = int(Decimal(str(previous["rate"])) * 100) + int(current["delta_bps"])
        actual_bps = int(Decimal(str(current["rate"])) * 100)
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
        if announced.tzinfo is None:
            announced = announced.replace(tzinfo=timezone.utc)
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
    fetch_feed: Callable[[], str] = fetch_media_release_feed,
    fetch_overview: Callable[[], str] = fetch_cash_rate_overview,
    now: Optional[datetime] = None,
) -> dict:
    """Reconcile immediate RSS, live overview, and historical table snapshots."""
    extras: list[dict] = []
    try:
        feed_decision = parse_media_release_feed(fetch_feed(), calendar)
        if feed_decision:
            extras.append(feed_decision)
    except RbaOfficialError:
        pass
    try:
        overview_decision = parse_cash_rate_overview(fetch_overview(), calendar)
        if overview_decision:
            extras.append(overview_decision)
    except RbaOfficialError:
        pass
    try:
        records = parse_cash_rate_table(fetch())
    except RbaOfficialError:
        # Network or upstream-table failure must not suppress otherwise-fresh
        # bank payloads. The merge invariant below still fails closed at the
        # instant a scheduled outcome is missing from every official source.
        records = []
    return merge_calendar(calendar, records, now=now, extra_decisions=extras)
