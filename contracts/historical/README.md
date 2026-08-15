# Legacy historical candidate v1

These contracts describe a dormant, read-only reconstruction of the preserved
CDR corpus. They do not authorize publication, promotion, replacement of a
rolling payload, or mutation of preserved source material.

Every retained observation is `partial`, has `promotion_eligible: false`, and
lists at least one blocker. Missing provider/register/attempt evidence uses the
typed `{ "state": "unavailable", "value": null, "reason": "..." }` form;
it is never represented as a measured zero.

Artifacts are identified by byte length and SHA-256. Paths are portable
snapshot-relative evidence locators, not network locations. No contract permits
URLs, publishers, releases, or a `latest` pointer.

The locked preservation population remains 1,932 files/25,586,769,110 bytes.
SQLite `-shm` and `-wal` files are separately locked as 176 transient evidence
files/4,305,785,896 bytes and are never candidate inputs. The remaining 1,756
critical files/21,280,983,214 bytes are immutable preservation evidence. The
actual union embedded in date source manifests is independently locked at
1,495 files/21,179,877,992 bytes. A full acceptance rehash covers the union of
critical evidence and candidate inputs, reports every drifted path, and blocks
acceptance; it does not silently drop the mismatch or rewrite evidence.
