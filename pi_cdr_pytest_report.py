"""Raw collection and terminal phase evidence for the protected sequential suite."""
from __future__ import annotations

import json
import hashlib
import os
import platform
import sys
from pathlib import Path

import pytest

SCHEMA = "ar-local-pytest-report-v1"


def pytest_addoption(parser):
    group = parser.getgroup("protected-canary")
    group.addoption("--canary-report", required=False)


def pytest_configure(config):
    path = config.getoption("canary_report")
    if not path:
        raise pytest.UsageError("protected reporter requires a unique report path")
    if os.path.lexists(path):
        raise pytest.UsageError("protected report already exists")
    config._canary_report = {"schema": SCHEMA, "complete": False, "collected": [],
                             "collection_skips": [], "collection_errors": [], "reports": [],
                             "errors": [], "collection_finished": False}
    config.pluginmanager.register(Reporter(config), "protected-canary-recorder")


def context(config):
    options = config.option
    selections = {name: getattr(options, name, None) for name in
                  ("keyword", "markexpr", "deselect", "ignore", "ignore_glob", "lf", "noconftest", "confcutdir")}
    if any(selections.values()):
        config._canary_report["errors"].append("selection override is forbidden")
    return {"source": str(config.rootpath), "inipath": str(config.inipath) if config.inipath else None,
            "ini": dict(config.inicfg), "python": str(Path(sys.executable).absolute()),
            "prefix": sys.prefix, "version": platform.python_version(), "platform": sys.platform,
            "cgroup": Path("/proc/self/cgroup").read_text() if sys.platform == "linux" else None,
            "pytest": pytest.__version__, "plugins": sorted(
                (dist.project_name, dist.version) for _, dist in config.pluginmanager.list_plugin_distinfo()),
            "reporter": {"path": str(Path(__file__).resolve()),
                         "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
            "environment": {name: os.environ.get(name) for name in
                            ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD")}}


class Reporter:
    def __init__(self, config):
        self.config = config
        self.value = config._canary_report

    def pytest_sessionstart(self, session):
        self.value["context"] = context(self.config)
        self.value["argv"] = list(self.config.invocation_params.args)
        self.value["collect_only"] = bool(self.config.option.collectonly)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, session, config, items):
        before = [item.nodeid for item in items]
        yield
        after = [item.nodeid for item in items]
        if sorted(before) != sorted(after) or len(set(before)) != len(before):
            self.value["errors"].append("collection filtered or duplicated node IDs")

    def pytest_collection_finish(self, session):
        self.value["collected"] = [{"nodeid": item.nodeid,
                                     "module": item.path.relative_to(self.config.rootpath).as_posix()}
                                    for item in session.items]
        self.value["collection_finished"] = True

    def pytest_collectreport(self, report):
        if report.failed or report.skipped:
            key = "collection_errors" if report.failed else "collection_skips"
            self.value[key].append({"nodeid": report.nodeid, "detail": str(report.longrepr)})

    def pytest_runtest_logreport(self, report):
        self.value["reports"].append({"nodeid": report.nodeid, "when": report.when,
                                     "outcome": report.outcome, "duration": report.duration,
                                     "wasxfail": getattr(report, "wasxfail", None),
                                     "detail": str(report.longrepr) if report.longrepr else ""})

    def pytest_internalerror(self, excrepr, excinfo):
        self.value["errors"].append("internal error: " + str(excrepr))

    def pytest_keyboard_interrupt(self, excinfo):
        self.value["errors"].append("interrupted: " + str(excinfo))

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        self.value["context_after"] = context(self.config)
        self.value.update(complete=True, exitstatus=int(session.exitstatus))
        path = Path(self.config.getoption("canary_report"))
        with path.open("x", encoding="utf-8") as stream:
            json.dump(self.value, stream, sort_keys=True)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
