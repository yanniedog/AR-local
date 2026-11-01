"""Validate full sequential suite evidence by node identity and terminal phases."""
from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from pi_cdr_quality_digest import read_digest

SCHEMA = "ar-local-sequential-pytest-v1"
BUDGET = 3600
HELPERS = ("pi_cdr_pytest_runner.py", "pi_cdr_pytest_report.py", "pi_cdr_pytest_proof.py")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def path_under(root: Path, name: str) -> Path:
    part = Path(name)
    require(bool(name) and not part.is_absolute() and ".." not in part.parts and "\\" not in name,
            "unsafe suite evidence path")
    result = root / part
    require(result.resolve() == result and not any(p.is_symlink() for p in (result, *result.parents)),
            "linked suite evidence path")
    return result


def read_body(path):
    return read_digest(path, capture=True, max_bytes=64 * 1024**2)[1]


def file_ref(root, path):
    info, _ = read_digest(path)
    return {"path": path.relative_to(root).as_posix(), "sha256": info.sha256, "bytes": info.size}


def referenced(root, reference):
    path = path_under(root, reference["path"])
    body = read_body(path)
    require(len(body) == reference["bytes"] and hashlib.sha256(body).hexdigest() == reference["sha256"],
            "suite evidence bytes changed")
    return body


def module_of(nodeid):
    name = nodeid.split("::", 1)[0]
    require(name.startswith("tests/") and name.endswith(".py") and ".." not in Path(name).parts
            and "\\" not in name, "collection node is not a whole test module")
    return name


def inventory(report):
    require(report.get("schema") == "ar-local-pytest-report-v1" and report.get("complete") is True
            and report.get("collection_finished") is True and not report.get("errors")
            and not report.get("collection_errors"), "incomplete or failed pytest collection")
    require(report["context_after"] == report["context"], "pytest context changed during session")
    nodes = report["collected"]
    require(len({row["nodeid"] for row in nodes}) == len(nodes), "duplicate collected node")
    for row in nodes:
        require(module_of(row["nodeid"]) == row["module"], "collection module mismatch")
    skips = report["collection_skips"]
    require(len({row["nodeid"] for row in skips}) == len(skips), "duplicate collection skip")
    for row in skips:
        module_of(row["nodeid"])
    return nodes, skips


def module_plan(report):
    nodes, skips = inventory(report)
    return sorted({row["module"] for row in nodes} | {module_of(row["nodeid"]) for row in skips})


def cases_for_batch(report, expected_nodes, expected_skips):
    nodes, skips = inventory(report)
    require(nodes == expected_nodes and skips == expected_skips, "batch collection differs from full inventory")
    require(report.get("collect_only") is False and report["exitstatus"] == (0 if nodes else 5),
            "failed or interrupted pytest batch")
    phases = {row["nodeid"]: [] for row in nodes}
    for row in report["reports"]:
        require(row["nodeid"] in phases, "unexpected runtime node")
        require(row["outcome"] in {"passed", "skipped"}, "failed test phase")
        require(type(row["duration"]) in (int, float) and math.isfinite(row["duration"])
                and row["duration"] >= 0, "invalid test duration")
        phases[row["nodeid"]].append(row)
    result = []
    for node in nodes:
        rows = phases[node["nodeid"]]
        require(len(rows) in (2, 3) and rows[0]["when"] == "setup", "missing terminal test phases")
        expected = ["setup", "teardown"] if rows[0]["outcome"] == "skipped" else ["setup", "call", "teardown"]
        require([row["when"] for row in rows] == expected,
                "missing, duplicate or failed teardown")
        skipped = next((row for row in rows if row["outcome"] == "skipped"), None)
        result.append({"nodeid": node["nodeid"], "module": node["module"],
                       "time": sum(row["duration"] for row in rows),
                       "skip": skipped["detail"] or skipped["wasxfail"] or "skipped" if skipped else None})
    result += [{"nodeid": "collection::" + row["nodeid"], "module": module_of(row["nodeid"]),
                "time": 0, "skip": row["detail"] or "collection skipped"} for row in skips]
    return result


def aggregate(cases):
    require(len({row["nodeid"] for row in cases}) == len(cases), "duplicate aggregate node")
    skipped = sum(row["skip"] is not None for row in cases)
    require(len(cases) > skipped, "empty or entirely skipped suite")
    suite = ET.Element("testsuite", name=SCHEMA, tests=str(len(cases)), failures="0", errors="0",
                       skipped=str(skipped), time=repr(sum(row["time"] for row in cases)))
    for row in cases:
        case = ET.SubElement(suite, "testcase", name=row["nodeid"], classname=row["module"], time=repr(row["time"]))
        if row["skip"] is not None:
            ET.SubElement(case, "skipped", message=row["skip"])
    return ET.tostring(suite, encoding="utf-8", xml_declaration=True)


def command(python, source, operation, selector, index, collect=False):
    report = operation / "pytest-suite" / index / "report.json"
    argv = [str(python), "-u", "-B", "-m", "pytest", selector, "-v", "-p", "no:cacheprovider",
            "-p", "pi_cdr_pytest_report", "--rootdir", str(source), "--basetemp",
            str(operation / "pytest-suite" / index / "tmp"), "--canary-report", str(report)]
    return argv + (["--collect-only"] if collect else [])


def validate_run(row, report, proof, selector, index, collect, previous_end):
    expected = command(proof["python"]["path"], Path(proof["source"]), Path(proof["operation"]),
                       selector, index, collect)
    require(row["command"] == expected and report["argv"] == expected[5:], "pytest command/context mismatch")
    require(row["report"]["path"] == f"pytest-suite/{index}/report.json"
            and row["log"]["path"] == f"pytest-suite/{index}/output.txt", "batch evidence path mismatch")
    require(row["group"] == proof["group"] and row["before"] == row["after"] == proof["owners"]
            and bool(proof["owners"]), "batch leaked descendants or changed supervisor ownership")
    require(row["returncode"] == report["exitstatus"], "pytest process/report exit mismatch")
    require(type(row["start"]) in (int, float) and type(row["end"]) in (int, float)
            and previous_end <= row["start"] <= row["end"] <= BUDGET, "overlapping or overdue pytest batch")
    return row["end"]


def validate_suite(root: Path, target: str, *, source=None, source_files=None, proof=None,
                   original_operation=None, resource_group=None):
    """Validate retained raw evidence; also works on byte-identical sealed copies."""
    proof = json.loads(read_body(root / "pytest-suite.json")) if proof is None else proof
    require(proof.get("schema") == SCHEMA and proof.get("result") == "PASS"
            and proof.get("target_commit") == target and re.fullmatch("[0-9a-f]{40}", target),
            "versioned exact-candidate suite proof required")
    require(proof["budget_seconds"] == BUDGET and 0 <= proof["elapsed_seconds"] <= BUDGET,
            "whole-suite deadline exceeded")
    require(proof["operation"] == str(original_operation or root), "suite operation mismatch")
    require(resource_group is None or proof["group"] == resource_group, "suite resource cgroup mismatch")
    require(re.fullmatch(r"/sys/fs/cgroup/system.slice/ar-local-quality-canary-[0-9a-f]{12}\.service", proof["group"])
            and all(re.fullmatch(r"[1-9][0-9]*", pid) and type(start) is int and start > 0
                    for pid, start in proof["owners"].items()), "invalid protected process ownership")
    require(source is None or proof["source"] == str(source), "suite source mismatch")
    files = proof["source_files"]
    require(bool(files) and (source_files is None or files == source_files), "suite source inventory mismatch")
    require(proof["helpers"] == {name: files[name] for name in HELPERS}, "runner/hook code binding mismatch")
    require(all(re.fullmatch("[0-9a-f]{64}", value) for value in [*files.values(), proof["python"]["sha256"]]),
            "invalid source/runtime digests")
    collection = json.loads(referenced(root, proof["collection"]["report"]))
    nodes, skips = inventory(collection)
    require(bool(nodes) and collection["collect_only"] is True and collection["exitstatus"] == 0
            and not collection["reports"], "full collection required before execution")
    expected_context = collection["context"]
    require(expected_context["reporter"] == {"path": str(Path(proof["source"]) / "pi_cdr_pytest_report.py"),
                                            "sha256": files["pi_cdr_pytest_report.py"]}, "unbound pytest reporter")
    require(expected_context["source"] == proof["source"]
            and expected_context["python"] == proof["python"]["path"], "collection interpreter/source mismatch")
    group = Path(proof["group"]).relative_to("/sys/fs/cgroup").as_posix()
    require(expected_context["platform"] == "linux" and expected_context["cgroup"] == "0::/" + group + "\n",
            "suite did not execute in the protected Linux cgroup")
    previous = validate_run(proof["collection"], collection, proof, "tests", "collect", True, 0)
    referenced(root, proof["collection"]["log"])
    modules = module_plan(collection)
    require([row["module"] for row in proof["batches"]] == modules, "missing/repeated/out-of-order module batch")
    cases = []
    for offset, row in enumerate(proof["batches"]):
        require(row["module"] in files, "test module absent from source inventory")
        report = json.loads(referenced(root, row["report"]))
        referenced(root, row["log"])
        require(report["context"] == expected_context, "pytest configuration/runtime changed between batches")
        previous = validate_run(row, report, proof, row["module"], f"{offset:05d}", False, previous)
        cases += cases_for_batch(report, [n for n in nodes if n["module"] == row["module"]],
                                 [s for s in skips if module_of(s["nodeid"]) == row["module"]])
    require(proof["aggregate"]["path"] == "pytest.xml" and previous <= proof["elapsed_seconds"]
            and referenced(root, proof["aggregate"]) == aggregate(cases),
            "aggregate does not match exact raw node/phase evidence")
    return proof


def evidence_names(proof):
    return ["pytest-suite.json", proof["aggregate"]["path"],
            *[row[key]["path"] for row in [proof["collection"], *proof["batches"]] for key in ("report", "log")]]
