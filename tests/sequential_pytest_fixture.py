"""Structural suite-provenance fixtures only; never producer/data acceptance."""
import copy
import hashlib
import json
import sys
from pathlib import Path

from pi_cdr_pytest_proof import BUDGET, HELPERS, SCHEMA, aggregate, cases_for_batch, command


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def reference(root, path):
    body = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}


def add_suite_source(source):
    repo = Path(__file__).resolve().parents[1]
    for name in HELPERS:
        (source / name).write_bytes((repo / name).read_bytes())
    (source / "tests").mkdir(exist_ok=True)
    (source / "tests/test_control.py").write_text("def test_control():\n    assert True\n", encoding="utf-8")


def suite_fixture(operation, source, target, files):
    """Like the existing synthetic PR/Jest controls: model evidence, not a run."""
    module = "tests/test_control.py"
    node = {"nodeid": module + "::test_control", "module": module}
    group = "/sys/fs/cgroup/system.slice/ar-local-quality-canary-0123456789ab.service"
    owners = {"123": 456}
    context = {"source": str(source), "python": str(Path(sys.executable).absolute()),
               "reporter": {"path": str(source / "pi_cdr_pytest_report.py"),
                            "sha256": files["pi_cdr_pytest_report.py"]},
               "platform": "linux", "cgroup": "0::/system.slice/ar-local-quality-canary-0123456789ab.service\n"}
    report = {"schema": "ar-local-pytest-report-v1", "complete": True, "collection_finished": True,
              "context": context, "context_after": copy.deepcopy(context), "errors": [],
              "collection_errors": [], "collection_skips": [], "collected": [node], "reports": [],
              "collect_only": True, "exitstatus": 0}
    rows, raw = [], []
    for offset, (index, selector, collect) in enumerate((("collect", "tests", True), ("00000", module, False))):
        value = copy.deepcopy(report)
        argv = command(sys.executable, source, operation, selector, index, collect)
        value.update(argv=argv[5:], collect_only=collect)
        if not collect:
            value["reports"] = [{"nodeid": node["nodeid"], "when": phase, "outcome": "passed",
                                 "duration": 0.01, "wasxfail": None, "detail": ""}
                                for phase in ("setup", "call", "teardown")]
        path = operation / "pytest-suite" / index
        save(path / "report.json", value)
        (path / "output.txt").write_text("Structural protocol fixture; no test execution claimed\n")
        rows.append({"module": selector, "command": argv, "returncode": 0, "start": offset,
                     "end": offset + 0.5, "group": group, "before": owners, "after": owners,
                     "report": reference(operation, path / "report.json"), "log": reference(operation, path / "output.txt")})
        raw.append(value)
    (operation / "pytest.xml").write_bytes(aggregate(cases_for_batch(raw[1], [node], [])))
    proof = {"schema": SCHEMA, "result": "PASS", "target_commit": target,
             "source": str(source), "operation": str(operation), "source_files": files,
             "helpers": {name: files[name] for name in HELPERS}, "budget_seconds": BUDGET,
             "elapsed_seconds": 2, "group": group, "owners": owners,
             "python": {"path": str(Path(sys.executable).absolute()),
                        "sha256": hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()},
             "collection": rows[0], "batches": [rows[1]], "aggregate": reference(operation, operation / "pytest.xml")}
    save(operation / "pytest-suite.json", proof)
    return proof
