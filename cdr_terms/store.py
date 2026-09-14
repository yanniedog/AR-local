"""Append-only private evidence storage with independently immutable blobs."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .discovery import discover_references, document_url
from .identity import byte_digest, canonical_json, digest, require_sha, timestamp


class EvidenceStore:
    """One private database plus content-addressed files, never a source DB.

    SQL denies UPDATE/DELETE even to accidental direct writes. Corrections are
    new records. OS permissions separate this controller from untrusted workers;
    the class is not a sandbox for model-generated code.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.root / "evidence.sqlite3", timeout=20)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=20000")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        application = self.db.execute("PRAGMA application_id").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise ValueError("Unsupported terms evidence schema version")
        if version and application != 0x4152544D:
            self.db.close()
            raise ValueError("Database is not an AR product terms evidence archive")
        if version == 0 and self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchone():
            self.db.close()
            raise ValueError("Refusing to migrate an existing non-terms database")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        tables = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for row in tables:
            # Names come only from this checked-in schema, never source strings.
            for operation in ("UPDATE", "DELETE"):
                self.db.execute(
                    f'CREATE TRIGGER IF NOT EXISTS "immutable_{row[0]}_{operation}" '
                    f'BEFORE {operation} ON "{row[0]}" BEGIN '
                    "SELECT RAISE(ABORT, 'terms evidence is append-only'); END"
                )
        self.db.execute("PRAGMA user_version=1")
        self.db.execute("PRAGMA application_id=1095914573")
        self.db.commit()

    def __enter__(self) -> "EvidenceStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.db.close()

    def put_blob(self, body: bytes) -> str:
        identity = byte_digest(body)
        target = self.blobs / identity[:2] / identity
        target.parent.mkdir(exist_ok=True, mode=0o700)
        if target.exists():
            self.read_blob(identity)
            return identity
        descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                self.read_blob(identity)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return identity

    def read_blob(self, identity: str) -> bytes:
        require_sha(identity)
        body = (self.blobs / identity[:2] / identity).read_bytes()
        if byte_digest(body) != identity:
            raise ValueError("Evidence blob integrity mismatch")
        return body

    def register_document(self, url: str) -> str:
        normalized = document_url(url)
        if normalized is None:
            raise ValueError("Document URL is not a public HTTP(S) reference")
        identity = digest({"source_url": normalized})
        self.db.execute("INSERT OR IGNORE INTO documents VALUES (?,?)", (identity, normalized))
        return identity

    def observe(self, *, provider: str, product_key: str, record: Mapping[str, Any],
                observed_at: str, ingest_id: str, source_bytes: bytes | None = None) -> str:
        if not provider or not product_key or not ingest_id:
            raise ValueError("Provider, product key and ingest identity are required")
        observed_at = timestamp(observed_at)
        body = source_bytes if source_bytes is not None else canonical_json(record).encode("utf-8")
        source = json.loads(body)
        source_record = source.get("data", source) if isinstance(source, dict) else source
        inner = record.get("data", record)
        if source_record != inner:
            raise ValueError("Source bytes do not bind the supplied product record")
        source_sha = self.put_blob(body)
        identity = digest([ingest_id, provider, product_key, observed_at, source_sha])
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)",
                            (identity, ingest_id, provider, product_key, observed_at, source_sha))
            for reference in discover_references(record):
                doc_id = self.register_document(reference.url)
                context = canonical_json(reference.as_dict())
                app_id = digest([identity, doc_id, reference.sourcePath, context])
                self.db.execute("INSERT OR IGNORE INTO applicability VALUES (?,?,?,?,?,?)",
                                (app_id, identity, doc_id, reference.sourcePath,
                                 reference.relation, context))
            links = source.get("links") if isinstance(source, dict) else None
            source_url = document_url(links.get("self")) if isinstance(links, dict) else None
            if source_url:
                self._record_cdr_source(identity, source_url, body, observed_at)
        return identity

    def _record_cdr_source(self, observation_id: str, url: str, body: bytes, observed_at: str) -> None:
        """The already acquired raw CDR response is itself scoped source evidence."""
        doc_id = self.register_document(url)
        context = canonical_json({"url": url, "sourcePath": "/links/self", "relation": "cdr_source"})
        app_id = digest([observation_id, doc_id, "/links/self", context])
        self.db.execute("INSERT OR IGNORE INTO applicability VALUES (?,?,?,?,?,?)",
                        (app_id, observation_id, doc_id, "/links/self", "cdr_source", context))
        self.record_check(document_id=doc_id, check_id=digest([observation_id, "source_response"]),
                          checked_at=observed_at, status="fetched", body=body, media_type="application/json",
                          metadata={"acquisition": "retained_cdr_source_response"})

    def record_check(self, *, document_id: str, check_id: str, checked_at: str,
                     status: str, body: bytes | None = None, media_type: str = "",
                     http_status: int | None = None, error_code: str | None = None,
                     metadata: Mapping[str, Any] | None = None,
                     previous_version_id: str | None = None) -> str | None:
        """Record a check; failures keep all old versions and do not remove terms."""
        checked_at = timestamp(checked_at)
        if not check_id:
            raise ValueError("Every acquisition attempt needs a durable unique key")
        version_id = None
        content_sha = None
        if status == "fetched":
            if not body:
                raise ValueError("A successful acquisition must retain nonempty original bytes")
            content_sha = self.put_blob(body)
            version_id = digest([document_id, content_sha])
        elif status == "unchanged":
            self._require_version(document_id, previous_version_id)
            version_id = previous_version_id
        elif body is not None or previous_version_id is not None:
            raise ValueError("Failed/deferred checks must not claim a document version")
        values = (check_id, document_id, checked_at, status, http_status, version_id,
                  error_code, canonical_json(dict(metadata or {})))
        existing = self.db.execute("SELECT * FROM acquisition_checks WHERE check_id=?", (check_id,)).fetchone()
        if existing:
            if tuple(existing)[1:] != values:
                raise ValueError("Attempt key reused with different evidence")
            return version_id
        with self.db:
            if content_sha:
                self.db.execute("INSERT OR IGNORE INTO document_versions VALUES (?,?,?,?,?,?,NULL,NULL)",
                                (version_id, document_id, content_sha, media_type, len(body), checked_at))
            self.db.execute("INSERT INTO acquisition_checks "
                            "(check_id,document_id,checked_at,status,http_status,document_version_id,error_code,metadata_json) "
                            "VALUES (?,?,?,?,?,?,?,?)", values)
        return version_id

    def _require_version(self, document_id: str, version_id: str | None) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM document_versions WHERE document_id=? AND document_version_id=?",
                              (document_id, version_id)).fetchone()
        if not row:
            raise ValueError("Unchanged response has no retained version for this document")
        self.read_blob(row["content_sha256"])
        return row

    def last_success(self, document_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM acquisition_checks WHERE document_id=? "
                              "AND status IN ('fetched','unchanged') ORDER BY checked_at DESC,sequence DESC LIMIT 1",
                              (document_id,)).fetchone()
        return dict(row) if row else None

    def register_extraction(self, *, document_version_id: str, extractor_version: str,
                            text: str, observed_at: str, status: str,
                            coverage: Mapping[str, Any]) -> str:
        if status == "complete" and (not text or coverage.get("unreadable_pages")):
            raise ValueError("Empty or unreadable extraction cannot be complete")
        text_sha = self.put_blob(text.encode("utf-8"))
        identity = digest([document_version_id, extractor_version, text_sha, status, coverage])
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO extractions VALUES (?,?,?,?,?,?,?)",
                            (identity, document_version_id, extractor_version, text_sha,
                             timestamp(observed_at), status, canonical_json(coverage)))
        return identity

    def add_clause(self, extraction_id: str, *, start: int, end: int,
                   page: int | None = None, section: str | None = None) -> str:
        row = self.db.execute("SELECT * FROM extractions WHERE extraction_id=?", (extraction_id,)).fetchone()
        if not row:
            raise ValueError("Clause requires a retained extraction")
        text = self.read_blob(row["text_sha256"]).decode("utf-8")
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                or (page is not None and (type(page) is not int or page < 1))):
            raise ValueError("Clause locator is outside its retained extraction")
        locator = {"start": start, "end": end}
        if page is not None:
            locator["page"] = page
        if section is not None:
            locator["section"] = section
        identity = digest([extraction_id, locator, text[start:end]])
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO clauses VALUES (?,?,?,?)",
                            (identity, extraction_id, canonical_json(locator), text[start:end]))
        return identity
