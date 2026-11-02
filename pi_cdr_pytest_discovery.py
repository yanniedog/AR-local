"""Pytest-owned directory discovery without retaining every imported test module."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from _pytest.reports import CollectReport


GLOBAL_HOOKS = (
    "pytest_collection", "pytest_collection_modifyitems", "pytest_collection_finish",
    "pytest_ignore_collect", "pytest_collect_directory", "pytest_collect_file",
    "pytest_pycollect_makemodule", "pytest_pycollect_makeitem", "pytest_make_collect_report", "pytest_collectstart",
    "pytest_collectreport", "pytest_itemcollected", "pytest_deselected", "pytest_generate_tests",
)


def identity():
    path = Path(__file__).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class Discovery:
    def __init__(self, config, reporter):
        self.config = config
        self.reporter = reporter
        self.value = config._canary_report
        self.seen = set()
        self.module_nodeids = {}
        self.terminal_modules = set()

    def terminal(self, report):
        module = self.module_nodeids.get(report.nodeid)
        if module is None:
            return  # Session, directory and class reports are not module outcomes.
        if module in self.terminal_modules:
            self.value["errors"].append("duplicate module terminal report: " + module)
        self.terminal_modules.add(module)
        if report.outcome not in ("passed", "skipped", "failed"):
            self.value["errors"].append("invalid module terminal outcome: " + module)
        self.value["module_outcomes"].append({"module": module, "outcome": report.outcome})

    def finish(self):
        self.audit()
        terminal = [row["module"] for row in self.value["module_outcomes"]]
        if terminal != self.value["collected_modules"]:
            message = "missing or reordered module terminal reports"
            if message not in self.value["errors"]:
                self.value["errors"].append(message)

    def audit(self):
        """Global hooks can change cross-module semantics; reject unknown owners."""
        for name in GLOBAL_HOOKS:
            for impl in getattr(self.config.hook, name).get_hookimpls():
                if impl.plugin is self or impl.plugin is self.reporter:
                    continue
                if impl.function.__module__.startswith("_pytest."):
                    continue
                message = "unsupported global collection hook: " + name
                if message not in self.value["errors"]:
                    self.value["errors"].append(message)
        return not self.value["errors"]

    def checked_path(self, collector):
        path = Path(collector.path).absolute()
        root = Path(self.config.rootpath).absolute()
        if path != root and root not in path.parents:
            raise pytest.Collector.CollectError("collector outside protected source")
        for part in (path, *path.parents):
            if part.is_symlink():
                raise pytest.Collector.CollectError("linked collection path")
            if part == root:
                break
        if path.resolve() != path:
            raise pytest.Collector.CollectError("noncanonical collection path")
        return path.relative_to(root).as_posix()

    @pytest.hookimpl(tryfirst=True)
    def pytest_make_collect_report(self, collector):
        try:
            return self.collect(collector)
        except pytest.Collector.CollectError as error:
            return CollectReport(collector.nodeid, "failed", str(error), [])

    def collect(self, collector):
        if not self.audit():
            raise pytest.Collector.CollectError("unsupported global collection hooks")
        # Reject custom collectors rather than silently omitting their items.
        allowed = type(collector) in (pytest.Session, pytest.Dir, pytest.Package, pytest.Module)
        allowed |= isinstance(collector, pytest.Class) and type(collector).__module__.startswith("_pytest.")
        if not allowed:
            raise pytest.Collector.CollectError("unexpected collection type: " + type(collector).__name__)
        relative = self.checked_path(collector)
        if isinstance(collector, pytest.Module):
            if not relative.startswith("tests/") or not relative.endswith(".py"):
                raise pytest.Collector.CollectError("unexpected non-Python test module")
            if relative in self.seen or collector.nodeid in self.module_nodeids:
                raise pytest.Collector.CollectError("duplicate collected module")
            self.seen.add(relative)
            self.module_nodeids[collector.nodeid] = relative
            self.value["collected_modules"].append(relative)
            if self.value["discovery"]:
                self.value["discovered_modules"].append(relative)
                return CollectReport(collector.nodeid, "passed", None, [])
        return None
