"""Real HTTP/schema fixtures, not business-data or live dashboard acceptance."""
import copy
import json
import subprocess
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
             "status": 200, "delay": 0, "header_delay": 0, "changes": {}, "length_extra": 0,
             "trickle_headers": False}
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
            if parsed.path.endswith('/compact') and state['trickle_headers']:
                try:
                    self.wfile.write(b'HTTP/1.0 200 OK\r\nX-Slow: ')
                    for _ in range(25):
                        self.wfile.write(b'x'); self.wfile.flush(); time.sleep(0.05)
                    self.wfile.write(b'\r\nContent-Length: 2\r\n\r\n{}')
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if parsed.path.endswith("/compact"):
                time.sleep(state["header_delay"])
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


def test_header_and_body_share_one_deadline(transport):
    # Headers spend part of the budget; body stalls beyond what remains. Reusing
    # the original socket timeout would wait about 1 second instead of 0.65.
    transport.update(header_delay=0.35, delay=0.7)
    url = transport["base"] + "api/banks/history/section/compact?date=" + DAY + "&section=Mortgage"
    started = time.monotonic()
    with pytest.raises((TimeoutError, ValueError)):
        compact.read_json(url, timeout=0.65)
    assert time.monotonic() - started < 0.9


@pytest.mark.parametrize('fault', ['changed_mean', 'changed_count', 'provider_total', 'zero_live_ribbon'])
def test_same_day_positive_but_stale_aggregate_is_fatal(transport, fault):
    def change(data):
        if fault == 'changed_mean':
            data['points'][0]['mean'] += 0.01
        elif fault == 'changed_count':
            data['points'][0]['count'] += 1
        elif fault == 'provider_total':
            data['providers'][0]['by_date'][DAY]['count'] += 1
        return data
    transport['change'] = change
    if fault == 'zero_live_ribbon':
        transport['changes']['ribbon'] = lambda data: responses(data['section'], standard=False)['ribbon']
    assert smoke(transport) == 1


def test_trickled_headers_cannot_extend_the_whole_request_deadline(transport):
    transport['trickle_headers'] = True
    url = transport['base'] + 'api/banks/history/section/compact?date=' + DAY + '&section=Mortgage'
    started = time.monotonic()
    with pytest.raises((TimeoutError, ValueError)):
        compact.read_json(url, timeout=0.3)
    assert time.monotonic() - started < 0.9


def test_aggregate_allows_only_summation_rounding_noise(transport):
    def change(data):
        data['points'][0]['mean'] += 1e-15
        return data
    transport['change'] = change
    assert smoke(transport) == 0


@pytest.mark.parametrize('interrupted', [False, True])
def test_network_worker_is_reaped_after_timeout_or_parent_interruption(transport, monkeypatch, interrupted):
    transport['trickle_headers'] = True
    children = []
    original = subprocess.Popen
    class ObservedChild(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            children.append(self)
        def communicate(self, *args, **kwargs):
            if interrupted:
                raise KeyboardInterrupt('parent interrupted')
            return super().communicate(*args, **kwargs)
    monkeypatch.setattr(compact.subprocess, 'Popen', ObservedChild)
    url = transport['base'] + 'api/banks/history/section/compact?date=' + DAY + '&section=Mortgage'
    with pytest.raises(KeyboardInterrupt if interrupted else TimeoutError):
        compact.read_json(url, timeout=0.3)
    assert len(children) == 1 and children[0].poll() is not None


def test_preconnection_worker_stall_is_also_bounded_and_reaped(tmp_path, monkeypatch):
    # Real child process fault fixture for a resolver/connect stall before headers;
    # no external DNS/network traffic or business-data substitution is involved.
    worker = tmp_path / 'blocked_transport.py'
    worker.write_text('import time\ntime.sleep(30)\n', encoding='utf-8')
    monkeypatch.setattr(compact, 'WORKER', worker)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        compact.read_json('http://test.invalid/', timeout=0.2)
    assert time.monotonic() - started < 1
