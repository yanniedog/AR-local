"""Real isolated pytest processes exercise discovery, without provider data."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[1]


def test_hook_audit_uses_raw_relay_and_preserves_external_hook_rejection():
    from _pytest.config import get_config
    from pi_cdr_pytest_discovery import Discovery

    config = get_config()
    raw = config.pluginmanager.hook

    class CompatibilityRelay:
        def __getattr__(self, name):
            hook = getattr(raw, name)
            if name == "pytest_ignore_collect":
                return lambda **kwargs: hook(**kwargs)
            return hook

    class ExternalPlugin:
        def pytest_ignore_collect(self, collection_path, config):
            return None

    config.hook = CompatibilityRelay()
    config._canary_report = {"errors": []}
    discovery = Discovery(config, object())
    try:
        assert not hasattr(config.hook.pytest_ignore_collect, "get_hookimpls")
        assert discovery.audit()
        config.pluginmanager.register(ExternalPlugin(), "external-test-hook")
        assert not discovery.audit()
        assert config._canary_report["errors"] == [
            "unsupported global collection hook: pytest_ignore_collect"]
    finally:
        config._ensure_unconfigure()


def tree(tmp_path, files):
    source = tmp_path / "source"
    source.mkdir()
    for name, text in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return source


def run(source, name, selectors=("tests",), *, discovery=False, partitioned=True, collect=True):
    report = source.parent / (name + ".json")
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=str(SOURCE))
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    command = [sys.executable, "-B", "-m", "pytest", *selectors, "-q", "-p", "no:cacheprovider",
               "-p", "pi_cdr_pytest_report", "--rootdir", str(source), "--canary-report", str(report),
               "--basetemp", str(source.parent / (name + "-tmp"))]
    if partitioned:
        command.append("--canary-partitioned")
    if discovery:
        command.append("--canary-discover-modules")
    if collect:
        command.append("--collect-only")
    result = subprocess.run(command, cwd=source, env=env, capture_output=True, text=True, timeout=30)
    return result, json.loads(report.read_text()) if report.exists() else None


def test_native_discovery_and_parameterized_partition_equivalence(tmp_path):
    source = tree(tmp_path, {
        "tests/test_a.py": "import pytest\n@pytest.mark.parametrize('x', [1,2])\ndef test_x(x): assert x\n",
        "tests/sub/test_b.py": "class TestGroup:\n def test_y(self): pass\n",
        "tests/test_empty.py": "VALUE = 1\n",
    })
    result, discovery = run(source, "discover", discovery=True)
    assert result.returncode == 5
    assert discovery["collected"] == []
    assert discovery["discovered_modules"] == ["tests/sub/test_b.py", "tests/test_a.py", "tests/test_empty.py"]
    assert discovery["collected_modules"] == discovery["discovered_modules"]
    assert discovery["module_outcomes"] == [{"module": m, "outcome": "passed"} for m in discovery["discovered_modules"]]
    _, whole = run(source, "whole")
    collected = []
    for i, module in enumerate(discovery["discovered_modules"]):
        result, part = run(source, "part" + str(i), [module])
        assert result.returncode == (0 if part["collected"] else 5)
        assert part["context"] == whole["context"] == discovery["context"]
        assert part["collected_modules"] == [module]
        assert part["module_outcomes"] == [{"module": module, "outcome": "passed"}]
        collected += part["collected"]
    assert collected == whole["collected"]
    assert len(collected) == 3
    assert not whole["errors"]


def test_native_config_and_conftest_ignores(tmp_path):
    source = tree(tmp_path, {
        "pytest.ini": "[pytest]\npython_files = check_*.py\nnorecursedirs = ignored\n",
        "tests/conftest.py": "collect_ignore = ['check_omit.py']\n",
        "tests/check_ok.py": "raise RuntimeError('must not import during discovery')\n",
        "tests/check_omit.py": "raise RuntimeError('ignored')\n",
        "tests/test_default.py": "raise RuntimeError('wrong pattern')\n",
        "tests/ignored/check_no.py": "raise RuntimeError('ignored dir')\n",
    })
    result, report = run(source, "discover", discovery=True)
    assert result.returncode == 5
    assert report["discovered_modules"] == ["tests/check_ok.py"]
    assert report["collection_errors"] == []


@pytest.mark.parametrize("body,expected", [("import pytest\npytest.skip('module skip', allow_module_level=True)\n", 5),
                                           ("raise RuntimeError('import error')\n", 2)])
def test_module_import_skip_or_failure_is_deferred_not_omitted(tmp_path, body, expected):
    source = tree(tmp_path, {"tests/test_a.py": body})
    result, discovery = run(source, "discover", discovery=True)
    assert result.returncode == 5 and discovery["discovered_modules"] == ["tests/test_a.py"]
    result, part = run(source, "part", ["tests/test_a.py"])
    assert result.returncode == expected
    assert part["collection_skips" if expected == 5 else "collection_errors"]
    assert part["collected_modules"] == ["tests/test_a.py"]
    assert part["module_outcomes"] == [{"module": "tests/test_a.py", "outcome": "skipped" if expected == 5 else "failed"}]


@pytest.mark.parametrize("hook", [
    "def pytest_collection_modifyitems(items): items.clear()\n",
    "def pytest_collection_modifyitems(items): items.extend(items)\n",
    "def pytest_ignore_collect(collection_path): return True\n",
    "def pytest_collect_file(file_path, parent): return None\n",
    "def pytest_generate_tests(metafunc): pass\n",
])
def test_unsupported_global_hooks_fail_closed_including_late_conftest(tmp_path, hook):
    source = tree(tmp_path, {"tests/sub/conftest.py": hook, "tests/sub/test_a.py": "def test_a(): pass\n"})
    result, report = run(source, "discover", discovery=True)
    assert result.returncode != 0
    assert any("unsupported global collection hook" in error for error in report["errors"])


def test_per_module_parametrization_hook_remains_supported(tmp_path):
    source = tree(tmp_path, {"tests/test_a.py": "def pytest_generate_tests(metafunc): metafunc.parametrize('x',[1,2])\ndef test_a(x): assert x\n"})
    result, report = run(source, "run", collect=False)
    assert result.returncode == 0 and len(report["collected"]) == 2
    assert not report["errors"]


def test_global_parametrization_can_differ_across_sessions_and_is_rejected(tmp_path):
    source = tree(tmp_path, {
        "tests/conftest.py": "counter = 0\ndef pytest_generate_tests(metafunc):\n global counter\n counter += 1\n metafunc.parametrize('x', [counter])\n",
        "tests/test_a.py": "def test_a(x): pass\n",
        "tests/test_b.py": "def test_b(x): pass\n",
    })
    _, whole = run(source, "legacy-whole", partitioned=False)
    _, alone = run(source, "legacy-alone", ["tests/test_b.py"], partitioned=False)
    assert [row for row in whole["collected"] if row["module"] == "tests/test_b.py"] != alone["collected"]
    result, guarded = run(source, "guarded")
    assert result.returncode != 0
    assert "unsupported global collection hook: pytest_generate_tests" in guarded["errors"]
    assert guarded["collected"] == []


def test_empty_module_receipt_records_native_visits_not_requested_selectors(tmp_path):
    source = tree(tmp_path, {"tests/test_empty.py": "VALUE = 1\n"})
    result, report = run(source, "duplicate", ["tests/test_empty.py", "tests/test_empty.py"])
    assert result.returncode == 5 and report["collected"] == []
    # Pytest caches this collector. The raw evidence must not fabricate a second
    # visit from argv; the proof's exact selector/visit equality rejects it.
    assert report["argv"].count("tests/test_empty.py") == 2
    assert report["collected_modules"] == ["tests/test_empty.py"]
    assert report["module_outcomes"] == [{"module": "tests/test_empty.py", "outcome": "passed"}]


@pytest.mark.parametrize("selectors", [["tests/test_a.py", "tests/test_a.py"], ["tests/test_a.py"]])
def test_discovery_duplicate_or_narrowed_selector_rejected(tmp_path, selectors):
    source = tree(tmp_path, {"tests/test_a.py": "def test_a(): pass\n"})
    result, report = run(source, "discover", selectors, discovery=True)
    assert result.returncode == 4 and report is None


@pytest.mark.parametrize("partitioned,collect", [(False, True), (True, False)])
def test_invalid_discovery_options_rejected(tmp_path, partitioned, collect):
    source = tree(tmp_path, {"tests/test_a.py": "def test_a(): pass\n"})
    result, report = run(source, "invalid", discovery=True, partitioned=partitioned, collect=collect)
    assert result.returncode == 4 and report is None


def test_v1_does_not_apply_new_hook_policy(tmp_path):
    source = tree(tmp_path, {"tests/conftest.py": "def pytest_collection_modifyitems(items): pass\n", "tests/test_a.py": "def test_a(): pass\n"})
    result, report = run(source, "legacy", partitioned=False)
    assert result.returncode == 0 and not report["errors"]
    assert not report["partitioned"] and "discovery_helper" not in report["context"]


def test_outside_source_collector_rejected(tmp_path):
    source = tree(tmp_path, {"tests/test_a.py": "def test_a(): pass\n"})
    outside = tmp_path / "test_outside.py"
    outside.write_text("def test_outside(): pass\n")
    result, report = run(source, "outside", [str(outside)])
    assert result.returncode != 0 and report["collection_errors"]
    assert "outside protected source" in str(report["collection_errors"])


def test_linked_module_rejected_without_import(tmp_path):
    source = tree(tmp_path, {"tests/test_a.py": "raise RuntimeError('must not import')\n"})
    try:
        (source / "tests/test_link.py").symlink_to(source / "tests/test_a.py")
    except OSError as error:
        pytest.skip("host cannot create test symlink: " + str(error))
    result, report = run(source, "linked", discovery=True)
    assert result.returncode != 5 and report["collection_errors"]
    assert "linked collection path" in str(report["collection_errors"])


@pytest.mark.parametrize("body,key", [("raise RuntimeError('directory configuration failure')\n", "collection_errors"),
                                      ("import pytest\npytest.skip('directory skipped', allow_module_level=True)\n", "collection_skips")])
def test_directory_collection_error_or_skip_is_retained(tmp_path, body, key):
    source = tree(tmp_path, {"tests/sub/conftest.py": body,
                             "tests/sub/test_a.py": "def test_a(): pass\n"})
    result, report = run(source, "directory-error", discovery=True)
    assert result.returncode != 0 and report[key]
    assert report[key][0]["nodeid"] == "tests/sub"


def test_non_python_collector_is_rejected(tmp_path):
    source = tree(tmp_path, {"pytest.ini": "[pytest]\naddopts = --doctest-glob=*.txt\n",
                             "tests/example.txt": ">>> 1\n1\n"})
    result, report = run(source, "non-python", discovery=True)
    assert result.returncode != 5 and report["collection_errors"]
    assert "unexpected collection type" in str(report["collection_errors"])
