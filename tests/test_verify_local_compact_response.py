"""Real HTTP/schema fixtures, not business-data or live dashboard acceptance."""
import copy
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

import verify_local
import verify_local_compact as compact
from cdr_ribbon_normalize import aggregate_ribbon, compact_history

DAY = "2026-09-13"
OLD = "2026-09-12"


def responses(section, *, standard=True, present=True):
    # Use the shipping serializer/kernel to represent the transport contract.
    rows = ([{"provider": "Transport fixture", "product_key": "fixture", "rate": "0.03",
              "account_class": "standard" if standard else "non_standard"}] if present else [])
    aggregate = aggregate_ribbon(rows if standard else [], section)
    return {
        "ribbon": {"run_date": DAY, "section": section, **aggregate},
        "section": {"run_date": DAY, "section": section, "rates": rows, "counts": {"rates": len(rows)}},
        "compact": {"run_date": DAY, "section": section, "include_non_standard": False,
                    **compact_history([DAY] if present else [], {DAY: aggregate})},
    }


@pytest.fixture
def transport():
    state = {"change": lambda data: data, "standard": True, "present": True, "paths": [],
             "status": 200, "delay": 0, "changes": {}, "length_extra": 0}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            state["paths"].append(parsed.path)
            status = 404 if parsed.path == "/api/energy" else 200
            payload = {}
            if parsed.path == "/api/latest":
                payload = {"run_date": DAY, "banks_counts": {"rates": 1}}
            elif parsed.path.startswith("/api/banks/"):
                section = parse_qs(parsed.query).get("section", [""])[0]
                kind = parsed.path.rsplit("/", 1)[-1]
                payload = responses(section, standard=state["standard"], present=state["present"]).get(kind, {})
                if kind == "compact":
                    status = state["status"]
                    payload = state["change"](copy.deepcopy(payload))
                payload = state["changes"].get(kind, lambda item: item)(payload)
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body) + (state["length_extra"]
                                                               if parsed.path.endswith("/compact") else 0)))
            self.end_headers()
            try:
                if parsed.path.endswith("/compact"):
                    time.sleep(state["delay"])
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    state["base"] = f"http://127.0.0.1:{server.server_port}/"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def smoke(transport):
    return verify_local.main(["--base-url=" + transport["base"], "--history-mode=compact",
                              "--expect-run-date=" + DAY, "--require-banks-rates"])


@pytest.mark.parametrize("value", [b"", b"{broken", b"<html>OK</html>", [], {},
                                   {"run_date": DAY, "section": "Mortgage"}])
def test_http_200_unusable_body_is_fatal(transport, value, capsys):
    transport["change"] = lambda _: value
    assert smoke(transport) == 1
    assert "compact" in capsys.readouterr().err


def test_echoed_current_date_with_stale_series_is_fatal(transport):
    def stale(data):
        data["run_dates"] = [OLD]
        data["points"][0]["date"] = OLD
        data["providers"][0]["by_date"] = {OLD: data["providers"][0]["by_date"][DAY]}
        return data
    transport["change"] = stale
    assert smoke(transport) == 1


def test_positive_ribbon_with_empty_current_point_is_fatal(transport):
    transport["change"] = lambda _: responses("Mortgage", standard=False)["compact"]
    assert smoke(transport) == 1


@pytest.mark.parametrize("standard,present", [(True, True), (False, True), (True, False)])
def test_shipped_contract_and_legitimate_empty_sections(transport, standard, present):
    transport.update(standard=standard, present=present)
    assert smoke(transport) == 0
    assert transport["paths"].count("/api/banks/history/section/compact") == 3
    assert "/api/banks/history/section" not in transport["paths"]


@pytest.mark.parametrize("key,value", [
    ("run_date", OLD), ("section", "TD"), ("include_non_standard", True),
    ("run_dates", []), ("points", []), ("providers", {}), ("points", [None]),
])
def test_wrong_envelope_or_series_shape_is_fatal(transport, key, value):
    transport["change"] = lambda data: {**data, key: value}
    assert smoke(transport) == 1


@pytest.mark.parametrize("field,value", [("count", True), ("count", -1), ("count", 0.5),
                                        ("mean", "bad"), ("mean", float("nan")), ("mean", None)])
def test_unusable_current_statistics_are_fatal(transport, field, value):
    def change(data):
        data["points"][0][field] = value
        return data
    transport["change"] = change
    assert smoke(transport) == 1


@pytest.mark.parametrize("kind", ["ribbon", "section"])
def test_expectation_responses_cannot_be_empty_or_from_another_section(transport, kind):
    transport["changes"][kind] = lambda data: {**data, "section": "wrong"}
    assert smoke(transport) == 1


def test_sparse_provider_dates_and_historical_nulls_are_valid(transport):
    def change(data):
        data["run_dates"].insert(0, OLD)
        data["points"].insert(0, {"date": OLD, "count": 0, **dict.fromkeys(compact.STATS)})
        data["providers"].append({"provider": "Historical fixture", "by_date": {
            OLD: {"count": 0, **dict.fromkeys(compact.STATS)}}})
        return data
    transport["change"] = change
    assert smoke(transport) == 0


@pytest.mark.parametrize("status", [404, 500, 503])
def test_real_http_error_is_fatal(transport, status):
    transport["status"] = status
    assert smoke(transport) == 1


def test_real_oversize_body_is_fatal(transport, capsys):
    transport["change"] = lambda _: b" " * (compact.MAX_JSON_BYTES + 1)
    assert smoke(transport) == 1
    assert "body limit" in capsys.readouterr().err


def test_real_delayed_body_is_fatal(transport):
    transport["delay"] = 0.2
    url = transport["base"] + "api/banks/history/section/compact?date=" + DAY + "&section=Mortgage"
    with pytest.raises((TimeoutError, ValueError)):
        compact.read_json(url, timeout=0.05)


def test_truncated_transport_cannot_pass_even_when_json_prefix_is_complete(transport):
    transport["length_extra"] = 1
    assert smoke(transport) == 1
