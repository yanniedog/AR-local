from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import app_payload
import app_payload_build
import app_payload_v2
import ar_local_pi_runtime
import pi_daily_sync


def _write_day(exports: Path, run_date: str, rates: list[dict]) -> None:
    day = exports / "dashboard-cache" / run_date
    day.mkdir(parents=True, exist_ok=True)
    (day / "banks.json").write_text(
        json.dumps({"rates": rates, "products": []}), encoding="utf-8"
    )


def _rate(
    key: str,
    value: float,
    *,
    dataset: str = "Mortgage",
    provider: str = "Bank",
    product_id: str = "",
    category: str = "",
) -> dict:
    return {
        "dataset": dataset,
        "provider": provider,
        "product_key": key,
        "product_id": product_id,
        "category": category,
        "rate": value,
        "rate_family": "lending" if dataset == "Mortgage" else "deposit",
    }


def _source_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _v1_manifest(run_date: str = "2026-07-31") -> dict:
    return {
        "schema_version": 1,
        "run_date": run_date,
        "files": {
            "core": {"sha256": "c" * 64},
            "details": {"sha256": "d" * 64},
        },
    }


def test_product_history_is_complete_aligned_and_does_not_mutate_ledger(tmp_path):
    exports = tmp_path / "runs" / "2026-07-31" / "_exports"
    _write_day(
        exports,
        "2026-07-29",
        [_rate("mortgage-a", 0.05), _rate("savings-b", 0.04, dataset="Savings")],
    )
    _write_day(
        exports,
        "2026-07-30",
        [_rate("mortgage-a", 0.051), _rate("td-c", 0.045, dataset="TD")],
    )
    _write_day(
        exports,
        "2026-07-31",
        [_rate("savings-b", 0.041, dataset="Savings")],
    )
    before = _source_hashes(exports)

    payload = app_payload_v2.build_product_history(exports, run_date="2026-07-31")

    assert payload["schema_version"] == 2
    assert payload["run_dates"] == ["2026-07-29", "2026-07-30", "2026-07-31"]
    assert payload["products"] == {
        "mortgage-a": [0.05, 0.051, None],
        "savings-b": [0.04, None, 0.041],
        "td-c": [None, 0.045, None],
    }
    assert payload["moves"]["mortgage-a"] == [
        {
            "date": "2026-07-30",
            "from_rate": 0.05,
            "to_rate": 0.051,
            "bps": 10.0,
        }
    ]
    # A real gap is retained. The later observation may still form a move, but no
    # value is invented for the missing date.
    assert payload["moves"]["savings-b"][0]["date"] == "2026-07-31"
    assert payload["coverage"] == {
        "date_count": 3,
        "product_count": 3,
        "identity_count": 3,
        "observation_count": 5,
        "move_count": 2,
        "unkeyed_rate_rows": 0,
        "first_date": "2026-07-29",
        "last_date": "2026-07-31",
    }
    assert _source_hashes(exports) == before


def test_product_rename_aliases_resolve_the_complete_stable_series(tmp_path):
    exports = tmp_path / "runs" / "2026-07-31" / "_exports"
    _write_day(
        exports,
        "2026-07-30",
        [
            _rate(
                "Bank|pid-1|SAVINGS_ACCOUNTS|Old name",
                0.04,
                dataset="Savings",
                product_id="pid-1",
                category="SAVINGS_ACCOUNTS",
            )
        ],
    )
    _write_day(
        exports,
        "2026-07-31",
        [
            _rate(
                "Bank|pid-1|SAVINGS_ACCOUNTS|New name",
                0.041,
                dataset="Savings",
                product_id="pid-1",
                category="SAVINGS_ACCOUNTS",
            )
        ],
    )

    payload = app_payload_v2.build_product_history(exports, run_date="2026-07-31")

    expected = [0.04, 0.041]
    assert payload["products"]["Bank|pid-1|SAVINGS_ACCOUNTS|Old name"] == expected
    assert payload["products"]["Bank|pid-1|SAVINGS_ACCOUNTS|New name"] == expected
    assert payload["coverage"]["identity_count"] == 1
    assert payload["coverage"]["observation_count"] == 4


def test_product_with_no_valid_rate_is_retained_as_an_explicit_null_series(tmp_path):
    exports = tmp_path / "runs" / "2026-07-31" / "_exports"
    _write_day(exports, "2026-07-30", [_rate("invalid-rate", 0)])
    _write_day(exports, "2026-07-31", [_rate("valid-rate", 0.05)])

    payload = app_payload_v2.build_product_history(exports, run_date="2026-07-31")

    assert payload["products"]["invalid-rate"] == [None, None]
    assert payload["products"]["valid-rate"] == [None, 0.05]
    assert payload["coverage"]["product_count"] == 2
    assert payload["coverage"]["observation_count"] == 1


def test_product_history_matches_legacy_percent_normalization_and_dataset_identity(tmp_path):
    exports = tmp_path / "runs" / "2026-07-31" / "_exports"
    _write_day(
        exports,
        "2026-07-31",
        [
            _rate(
                "Bank|same-id|SAVINGS|Savings",
                5.5,
                dataset="Savings",
                product_id="same-id",
                category="DEPOSITS",
            ),
            _rate(
                "Bank|same-id|TD|Term",
                4.8,
                dataset="TD",
                product_id="same-id",
                category="DEPOSITS",
            ),
        ],
    )

    payload = app_payload_v2.build_product_history(exports, run_date="2026-07-31")

    assert payload["products"]["Bank|same-id|SAVINGS|Savings"] == [0.055]
    assert payload["products"]["Bank|same-id|TD|Term"] == [0.048]
    assert payload["coverage"]["identity_count"] == 2


def test_build_v2_sidecar_matches_locked_wire_contract(tmp_path):
    exports = tmp_path / "runs" / "2026-07-31" / "_exports"
    _write_day(exports, "2026-07-31", [_rate("mortgage-a", 0.05)])
    out = tmp_path / "state" / "app-payload" / "v2"

    manifest = app_payload_v2.build_v2_sidecar(
        exports, out, v1_manifest=_v1_manifest()
    )

    assert set(manifest) == {
        "schema_version",
        "run_date",
        "generated_at",
        "base",
        "files",
    }
    assert manifest["schema_version"] == 2
    assert manifest["base"] == {
        "manifest_schema": 1,
        "core_sha": "c" * 64,
        "details_sha": "d" * 64,
    }
    descriptor = manifest["files"]["product_history"]
    assert set(descriptor) == {"name", "sha256", "bytes", "encoding", "url"}
    assert descriptor["encoding"] == "gzip"
    stored = (out / descriptor["name"]).read_bytes()
    assert hashlib.sha256(stored).hexdigest() == descriptor["sha256"]
    payload = json.loads(gzip.decompress(stored))
    assert payload["core_sha"] == "c" * 64
    assert payload["products"] == {"mortgage-a": [0.05]}
    assert (out / app_payload_v2.V2_MANIFEST_FILENAME).is_file()
    assert not (out / "manifest.json").exists()


def _synthetic_v1_data(run_date: str) -> dict:
    return {
        "core": {
            "schema_version": 1,
            "run_date": run_date,
            "sections": {},
            "brands": {},
            "rba": {},
        },
        "details": {"schema_version": 1, "run_date": run_date, "products": {}},
        "run_date": run_date,
        "counts": {"products": 0},
        "search_index": None,
        "history_banks": None,
        "bank_history": None,
        "rba_calendar": None,
    }


def test_state_staging_keeps_v1_bytes_identical(tmp_path, monkeypatch):
    run_date = "2026-07-31"
    legacy_exports = tmp_path / "legacy" / "runs" / run_date / "_exports"
    state_exports = tmp_path / "state-run" / "runs" / run_date / "_exports"
    for exports in (legacy_exports, state_exports):
        cache = exports / "dashboard-cache"
        cache.mkdir(parents=True)
        (cache / "latest.json").write_text(
            json.dumps({"run_date": run_date}), encoding="utf-8"
        )

    monkeypatch.setattr(
        app_payload, "_compute_payload", lambda *_a, **_k: _synthetic_v1_data(run_date)
    )
    monkeypatch.setattr(app_payload, "publish_payload", lambda *_a, **_k: False)
    monkeypatch.setattr(
        app_payload, "_live_manifest_status", lambda *_a, **_k: ("missing", None)
    )
    monkeypatch.setattr(app_payload_build, "utc_now_iso", lambda: "2026-07-31T00:00:00Z")
    monkeypatch.setattr(app_payload_build, "_ingest_schedule", lambda: {"label": "Daily"})

    legacy_dated = tmp_path / "legacy-dated"
    app_payload.build_and_publish_dual(legacy_exports, out_dir=legacy_dated)
    state_root = tmp_path / "runtime-state"
    app_payload.build_and_publish_dual(state_exports, state_dir=state_root)

    assert (legacy_dated / "manifest.json").read_bytes() == (
        state_root / "v1-dated" / "manifest.json"
    ).read_bytes()
    assert (
        legacy_exports / "app-payload-latest" / "manifest.json"
    ).read_bytes() == (state_root / "v1-latest" / "manifest.json").read_bytes()
    assert not (state_exports / "app-payload").exists()
    assert not (state_exports / "app-payload-latest").exists()


def test_publish_v2_uploads_manifest_last_and_prunes_only_v2(tmp_path, monkeypatch):
    payload_dir = tmp_path / "v2"
    payload_dir.mkdir()
    data_name = "v2-product-history-2026-07-31-abc.json.gz"
    (payload_dir / data_name).write_bytes(b"payload")
    (payload_dir / "manifest-v2.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "run_date": "2026-07-31",
                "files": {"product_history": {"name": data_name}},
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        cmd = [str(value) for value in command]
        calls.append(cmd)
        if "--json" in cmd and "assets" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(app_payload_v2, "_gh_available", lambda: "gh")
    monkeypatch.setattr(app_payload_v2, "_gh_authed", lambda _gh: True)
    monkeypatch.setattr(
        app_payload_v2, "_live_v2_manifest_status", lambda *_a: ("missing", None)
    )
    monkeypatch.setattr(app_payload_v2.subprocess, "run", fake_run)
    pruned: list[set[str]] = []
    monkeypatch.setattr(
        app_payload_v2,
        "_prune_v2_assets",
        lambda _gh, _repo, _tag, keep: pruned.append(keep) or 0,
    )

    assert app_payload_v2.publish_v2_sidecar(payload_dir) is True

    upload_calls = [call for call in calls if call[1:3] == ["release", "upload"]]
    assert Path(upload_calls[0][4]).name == data_name
    assert Path(upload_calls[-1][4]).name == "manifest-v2.json"
    assert "--clobber" in upload_calls[-1]
    assert pruned == [{data_name}]


def test_v2_pruner_never_deletes_v1_assets(monkeypatch):
    rows = [
        "core-2026-07-31-aaa.json.gz\t2026-07-31T00:00:00Z",
        "details-2026-07-31-bbb.json.gz\t2026-07-31T00:00:00Z",
    ]
    rows.extend(
        f"v2-product-history-2026-07-{day:02d}-sha.json.gz"
        f"\t2026-07-{day:02d}T00:00:00Z"
        for day in range(20, 31)
    )
    deleted: list[str] = []

    def fake_run(command, **_kwargs):
        cmd = [str(value) for value in command]
        if "delete-asset" in cmd:
            deleted.append(cmd[4])
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="\n".join(rows), stderr="")

    monkeypatch.setattr(app_payload_v2.subprocess, "run", fake_run)
    count = app_payload_v2._prune_v2_assets("gh", "owner/repo", "tag", set())

    assert count == 3
    assert deleted
    assert all(name.startswith("v2-product-history-") for name in deleted)


def test_pi_v2_failure_is_nonfatal_after_v1_publish(tmp_path, monkeypatch, capsys):
    exports = tmp_path / "runs" / "2026-07-31" / "_exports"
    exports.mkdir(parents=True)
    staged: dict[str, Path] = {}
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    monkeypatch.setattr(ar_local_pi_runtime, "data_runs_root", lambda _repo: tmp_path / "runs")
    monkeypatch.setattr(ar_local_pi_runtime, "latest_exports_root", lambda _runs: exports)
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path / "state")
    def fake_v1(*_args, **kwargs):
        staged["v1"] = kwargs["state_dir"]
        return _v1_manifest(), True, True

    monkeypatch.setattr(app_payload, "build_and_publish_dual", fake_v1)
    monkeypatch.setattr(
        app_payload,
        "build_and_publish_v2",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("v2 boom")),
    )
    monkeypatch.setattr(
        app_payload,
        "refresh_dates_index",
        lambda *_a, **kwargs: staged.setdefault("dates", kwargs["out_dir"]) or False,
    )

    pi_daily_sync.maybe_publish_app_payload(tmp_path)

    output = capsys.readouterr().out
    assert "app_payload publish finished" in output
    assert "v2 failed (non-fatal; v1 preserved)" in output
    assert staged == {
        "v1": tmp_path / "state" / "app-payload" / "v1",
        "dates": tmp_path / "state" / "app-payload" / "v1-dates-index",
    }


def test_pi_backfills_v2_when_live_v1_exactly_matches(tmp_path, monkeypatch, capsys):
    exports = tmp_path / "runs" / "2026-07-31" / "_exports"
    exports.mkdir(parents=True)
    v1 = _v1_manifest()
    called: list[Path] = []
    monkeypatch.setenv("AR_LOCAL_APP_PAYLOAD", "1")
    monkeypatch.setattr(ar_local_pi_runtime, "data_runs_root", lambda _repo: tmp_path / "runs")
    monkeypatch.setattr(ar_local_pi_runtime, "latest_exports_root", lambda _runs: exports)
    monkeypatch.setattr(pi_daily_sync, "data_state_root", lambda _repo: tmp_path / "state")
    monkeypatch.setattr(
        app_payload, "build_and_publish_dual", lambda *_a, **_k: (v1, False, False)
    )
    monkeypatch.setattr(
        app_payload, "_live_manifest_status", lambda *_a: ("present", v1)
    )
    monkeypatch.setattr(
        app_payload,
        "build_and_publish_v2",
        lambda _exports, **kwargs: (
            called.append(kwargs["out_dir"]) or {"run_date": "2026-07-31"},
            True,
        ),
    )

    pi_daily_sync.maybe_publish_app_payload(tmp_path)

    assert called == [tmp_path / "state" / "app-payload" / "v2"]
    assert "app_payload v2 finished" in capsys.readouterr().out
