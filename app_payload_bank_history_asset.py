"""Lazy, core-bound historical catalogue transport outside legacy eager files."""
from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import re
from datetime import date

NAMESPACE = "bank_rate_history_catalogue"
ASSET_KIND = "bank-rate-history-catalogue"
INNER_GZIP_MAX_BYTES = 16 * 1024 * 1024
INNER_JSON_MAX_BYTES = 128 * 1024 * 1024
OUTER_GZIP_MAX_BYTES = 8 * 1024 * 1024
OUTER_JSON_MAX_BYTES = 24 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def critical_core(core):
    """Never put either historical archive on a legacy client's startup path."""
    return {key: value for key, value in core.items()
            if key not in ("bank_rate_history", NAMESPACE)}


def encode_envelope(catalogue, *, run_date, core_sha256):
    if not isinstance(catalogue, dict) or catalogue.get("schema_version") != 2:
        raise ValueError("Historical catalogue must use schema 2")
    if (date.fromisoformat(run_date).isoformat() != run_date
            or not HASH.fullmatch(core_sha256)):
        raise ValueError("Historical envelope date or core binding is invalid")
    decoded = canonical(catalogue)
    if not 0 < len(decoded) <= INNER_JSON_MAX_BYTES:
        raise ValueError("Historical catalogue decoded bytes exceed budget")
    compressed = gzip.compress(decoded, mtime=0)
    if len(compressed) > INNER_GZIP_MAX_BYTES:
        raise ValueError("Historical catalogue compressed bytes exceed budget")
    envelope = {"schema_version": 1, "run_date": run_date, "core_sha256": core_sha256,
                "catalogue": {"sha256": digest(decoded), "bytes": len(decoded),
                              "gzip_base64": base64.b64encode(compressed).decode("ascii")}}
    raw = canonical(envelope)
    if len(raw) > OUTER_JSON_MAX_BYTES:
        raise ValueError("Historical envelope decoded bytes exceed budget")
    wire = gzip.compress(raw, mtime=0)
    if len(wire) > OUTER_GZIP_MAX_BYTES:
        raise ValueError("Historical envelope compressed bytes exceed budget")
    return wire


def _inflate(raw, limit):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
        decoded = compressed.read(limit + 1)
    if len(decoded) > limit:
        raise ValueError("Historical asset decoded bytes exceed budget")
    return decoded


def _document(raw):
    def unique(pairs):
        value = {}
        for key, entry in pairs:
            if key in value:
                raise ValueError("Historical document has duplicate fields")
            value[key] = entry
        return value
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite history value")))


def decode_envelope(raw, *, run_date, core_sha256):
    """Verify both byte domains and current-core authority before adopting data."""
    if not 0 < len(raw) <= OUTER_GZIP_MAX_BYTES:
        raise ValueError("Historical envelope compressed bytes exceed budget")
    value = _document(_inflate(raw, OUTER_JSON_MAX_BYTES))
    if (not isinstance(value, dict) or set(value) != {"schema_version", "run_date", "core_sha256", "catalogue"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["run_date"] != run_date or value["core_sha256"] != core_sha256):
        raise ValueError("Historical envelope differs from its selected core")
    archive = value["catalogue"]
    if (not isinstance(archive, dict) or set(archive) != {"sha256", "bytes", "gzip_base64"}
            or not isinstance(archive["sha256"], str) or not HASH.fullmatch(archive["sha256"])
            or type(archive["bytes"]) is not int or not 0 < archive["bytes"] <= INNER_JSON_MAX_BYTES
            or not isinstance(archive["gzip_base64"], str)
            or len(archive["gzip_base64"]) > 4 * ((INNER_GZIP_MAX_BYTES + 2) // 3)):
        raise ValueError("Historical archive descriptor is invalid")
    compressed = base64.b64decode(archive["gzip_base64"], validate=True)
    if (len(compressed) > INNER_GZIP_MAX_BYTES
            or base64.b64encode(compressed).decode("ascii") != archive["gzip_base64"]):
        raise ValueError("Historical archive base64 is not canonical or exceeds budget")
    decoded = _inflate(compressed, archive["bytes"])
    if len(decoded) != archive["bytes"] or digest(decoded) != archive["sha256"]:
        raise ValueError("Historical catalogue decoded bytes differ from receipt")
    catalogue = _document(decoded)
    if not isinstance(catalogue, dict) or catalogue.get("schema_version") != 2:
        raise ValueError("Historical catalogue must use schema 2")
    return catalogue


def descriptor(manifest):
    namespace = manifest[NAMESPACE]
    if (not isinstance(namespace, dict) or set(namespace) != {"schema_version", "file"}
            or type(namespace["schema_version"]) is not int or namespace["schema_version"] != 1):
        raise ValueError("Historical namespace must use schema 1 with one file")
    entry = namespace["file"]
    if (not isinstance(entry, dict) or not {"name", "bytes", "sha256", "url"}.issubset(entry)
            or set(entry) - {"name", "bytes", "sha256", "url", "enc"}
            or not isinstance(entry["sha256"], str) or not HASH.fullmatch(entry["sha256"])
            or type(entry["bytes"]) is not int or not 0 < entry["bytes"] <= OUTER_GZIP_MAX_BYTES):
        raise ValueError("Historical asset descriptor is invalid")
    enc = entry.get("enc")
    if "enc" in entry and (not isinstance(enc, dict) or set(enc) != {"alg", "key_id"}
            or enc.get("alg") != "aes-256-gcm" or not isinstance(enc.get("key_id"), str)
            or not re.fullmatch(r"[0-9a-f]{8}", enc["key_id"])):
        raise ValueError("Historical asset encryption descriptor is invalid")
    if enc != manifest.get("files", {}).get("core", {}).get("enc"):
        raise ValueError("Historical asset and core encryption differ")
    expected = f"{ASSET_KIND}-{manifest.get('run_date')}-{entry['sha256'][:12]}.json.gz" + (".enc" if enc else "")
    if entry["name"] != expected or not isinstance(entry["url"], str):
        raise ValueError("Historical asset name/date/hash differs")
    repo, tag = manifest.get("repo"), manifest.get("tag")
    if (not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
            or not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", tag)
            or entry["url"] != f"https://github.com/{repo}/releases/download/{tag}/{expected}"):
        raise ValueError("Historical asset URL leaves its manifest release")
    return entry


def validate_local_asset(manifest, root):
    entry = descriptor(manifest)
    raw = (root / entry["name"]).read_bytes()
    if entry.get("enc"):
        import payload_crypto
        key = payload_crypto.resolve_key_from_env()
        if key is None or payload_crypto.key_id(key) != entry["enc"]["key_id"]:
            raise ValueError("Historical asset requires its private build encryption key")
        raw = payload_crypto.decrypt_asset(raw, key)
    decode_envelope(raw, run_date=manifest["run_date"], core_sha256=manifest["files"]["core"]["sha256"])


def retag_namespace(manifest, *, url):
    """Copy only the routing field; never change a catalogue's byte identity."""
    if NAMESPACE in manifest:
        namespace = manifest[NAMESPACE]
        entry = namespace["file"]
        manifest[NAMESPACE] = {**namespace, "file": {**entry, "url": url(entry["name"])}}
