"""Every local script referenced by the actual page must be served by its handler."""
from html.parser import HTMLParser
import sys
from urllib.parse import urlsplit

import pytest

import cdr_dashboard_server as server
from tests.test_cdr_dashboard_history_coverage import handler


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        source = dict(attrs).get("src", "")
        if tag == "script" and source.startswith("/") and not source.startswith("//"):
            self.paths.append(urlsplit(source).path)


def test_dashboard_referenced_scripts_are_served_exactly(tmp_path):
    instance = handler(tmp_path / "runs", tmp_path)
    page, content_type, _ = instance.route("/", {})
    assert content_type.startswith("text/html")
    scripts = Scripts()
    scripts.feed(page.decode("utf-8"))
    assert "/assets/history-transport.js" in scripts.paths
    assert '/site/theme.js' in scripts.paths
    for path in scripts.paths:
        if path.startswith('/site/'):
            target = tmp_path / 'site' / path.removeprefix('/site/')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('// Technical static-route fixture: ' + path, encoding='utf-8')
        else:
            target = server.DASHBOARD_ROOT / path.removeprefix('/assets/')
        body, content_type, _ = instance.route(path, {})
        assert content_type.partition(';')[0] in ('application/javascript', 'text/javascript'), path
        assert body == target.read_bytes(), path
        assert body, path


@pytest.mark.parametrize('fault', ['missing', 'wrong_type', 'wrong_body'])
def test_site_script_fault_is_detected(tmp_path, monkeypatch, fault):
    real_handler = handler
    def broken(*args):
        instance = real_handler(*args)
        route = instance.route
        def checked(path, query):
            if path == '/site/theme.js':
                if fault == 'missing':
                    raise FileNotFoundError(path)
                body, kind, *rest = route(path, query)
                return (b'wrong' if fault == 'wrong_body' else body,
                        'text/html' if fault == 'wrong_type' else kind, *rest)
            return route(path, query)
        instance.route = checked
        return instance
    monkeypatch.setattr(sys.modules[__name__], 'handler', broken)
    with pytest.raises((AssertionError, FileNotFoundError)):
        test_dashboard_referenced_scripts_are_served_exactly(tmp_path)
