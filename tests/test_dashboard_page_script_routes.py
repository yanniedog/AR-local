"""Every local script referenced by the actual page must be served by its handler."""
from html.parser import HTMLParser

import cdr_dashboard_server as server
from tests.test_cdr_dashboard_history_coverage import handler


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        source = dict(attrs).get("src", "")
        if tag == "script" and source.startswith("/assets/"):
            self.paths.append(source)


def test_dashboard_referenced_scripts_are_served_exactly(tmp_path):
    instance = handler(tmp_path / "runs", tmp_path)
    page, content_type, _ = instance.route("/", {})
    assert content_type.startswith("text/html")
    scripts = Scripts()
    scripts.feed(page.decode("utf-8"))
    assert "/assets/history-transport.js" in scripts.paths
    for path in scripts.paths:
        body, content_type, _ = instance.route(path, {})
        assert content_type.startswith("application/javascript"), path
        assert body == (server.DASHBOARD_ROOT / path.removeprefix("/assets/")).read_bytes(), path
        assert body, path
