"""Producer-compiled exact history cohorts; publication fails without readiness."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
import shutil
import subprocess

from app_payload_bank_history_asset import canonical, digest, _encode_document, _decode_document
from app_payload_bank_history_packed_asset import url_free_descriptor

NAMESPACE = "bank_rate_history_ready"
ASSET_KIND = "bank-rate-history-ready"
SEMANTIC_REVISION = "ar-history-ready-v1"
INNER_JSON_MAX_BYTES = 4 * 1024 * 1024
OUTER_JSON_MAX_BYTES = 2 * 1024 * 1024
ASSET_MAX_BYTES = 1024 * 1024
COMPILER_ROOT = Path(__file__).parent / "contracts" / "history_ready"


def compiler_identity():
    """Only the reviewed vendored compiler can grant semantic readiness."""
    compiler = COMPILER_ROOT / "compiler.cjs"
    metadata = json.loads((COMPILER_ROOT / "compiler-manifest.json").read_bytes())
    identity = digest(compiler.read_bytes())
    if metadata.get("sha256") != identity or metadata.get("semantic_revision") != SEMANTIC_REVISION:
        raise ValueError("Ready history compiler differs from its reviewed pin")
    return compiler, identity


@lru_cache(maxsize=1)
def node_runtime():
    node = shutil.which("node")
    if not node:
        raise ValueError("Ready history requires Node.js 24 or newer; publication deferred")
    version = subprocess.run([node, "--version"], capture_output=True, check=True, timeout=10).stdout.decode("ascii").strip()
    if not version.startswith("v") or int(version[1:].split(".")[0]) < 24:
        raise ValueError("Ready history requires Node.js 24 or newer; publication deferred")
    return node


def _invoke(document, *, validate=False):
    compiler, identity = compiler_identity()
    arguments = [node_runtime(), str(compiler)] + (["--validate"] if validate else [])
    try:
        result = subprocess.run(arguments, input=canonical(document), capture_output=True, timeout=120, check=False)
    except subprocess.TimeoutExpired as error:
        raise ValueError("Ready history compiler exceeded its deadline; publication deferred") from error
    if result.returncode:
        # Compiler stderr can contain source text. Keep it out of public logs.
        raise ValueError("Ready history semantic compilation/validation failed; publication deferred")
    if validate:
        return identity
    if not 0 < len(result.stdout) <= INNER_JSON_MAX_BYTES:
        raise ValueError("Ready history decoded bytes exceed the processing budget; publication deferred")
    value = json.loads(result.stdout)
    if value.get("semantic_revision") != SEMANTIC_REVISION or value.get("compiler_sha256") != identity:
        raise ValueError("Ready history compiler output is not bound to reviewed semantics")
    return value


def compile_ready(catalogue):
    return _invoke(catalogue)


def encode_envelope(catalogue, *, run_date, core_sha256):
    try:
        return _encode_document(compile_ready(catalogue), run_date=run_date, core_sha256=core_sha256,
                                inner_limit=INNER_JSON_MAX_BYTES, outer_json_limit=OUTER_JSON_MAX_BYTES,
                                outer_gzip_limit=ASSET_MAX_BYTES)
    except ValueError as error:
        raise ValueError(f"Ready history publication deferred: {error}") from error


def decode_envelope(raw, *, run_date, core_sha256):
    ready = _decode_document(raw, run_date=run_date, core_sha256=core_sha256,
                             inner_limit=INNER_JSON_MAX_BYTES, outer_json_limit=OUTER_JSON_MAX_BYTES,
                             outer_gzip_limit=ASSET_MAX_BYTES)
    _, identity = compiler_identity()
    if (not isinstance(ready, dict) or ready.get("semantic_revision") != SEMANTIC_REVISION
            or ready.get("compiler_sha256") != identity):
        raise ValueError("Ready history receipt requires the exact reviewed compiler")
    _invoke(ready, validate=True)
    return ready


def descriptor(manifest):
    entry = url_free_descriptor(manifest, NAMESPACE, ASSET_KIND)
    if entry["bytes"] > ASSET_MAX_BYTES:
        raise ValueError("Ready history asset bytes exceed the processing budget")
    return entry


def validate_local_asset(manifest, root):
    entry = descriptor(manifest)
    raw = (root / entry["name"]).read_bytes()
    if entry.get("enc"):
        import payload_crypto
        key = payload_crypto.resolve_key_from_env()
        if key is None or payload_crypto.key_id(key) != entry["enc"]["key_id"]:
            raise ValueError("Ready historical asset requires its private build encryption key")
        raw = payload_crypto.decrypt_asset(raw, key)
    return decode_envelope(raw, run_date=manifest["run_date"], core_sha256=manifest["files"]["core"]["sha256"])


def add_ready_asset(manifest, catalogue, out_dir, release_base, enc_key, write_asset):
    """Ready cohorts precede optional packed raw history; never silently omit."""
    from app_payload_network_budget import ROLLING_TOTAL_MAX_BYTES
    from app_payload_optional_assets import iter_payload_assets
    wire = encode_envelope(catalogue, run_date=manifest["run_date"], core_sha256=manifest["files"]["core"]["sha256"])
    entry = write_asset(out_dir, ASSET_KIND, manifest["run_date"], wire, release_base, enc_key)
    if entry["bytes"] > ASSET_MAX_BYTES:
        raise ValueError("Ready history transport exceeds the processing budget; publication deferred")
    if sum(asset["bytes"] for _, asset in iter_payload_assets(manifest)) + entry["bytes"] > ROLLING_TOTAL_MAX_BYTES:
        raise ValueError("Ready history exceeds the combined transfer budget; publication deferred")
    manifest[NAMESPACE] = {"schema_version": 1, "file": {key: value for key, value in entry.items() if key != "url"}}
