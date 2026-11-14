# Current facts and change replay

`cdr_outputs.build_outputs` stores complete normalized fact/change rows in a new
private SQLite replay directory while building exports. Direct callers of
`parse_banks_run` retain the existing list interface unless they supply a sink.
This changes intermediate storage, not the normalized schema, event rules or
financial coverage.

The facts export retains source traversal and row order, including duplicate
rows. Product diffs retain exact stripped case-sensitive identities and the
existing per-product algorithm. Missing-product suppression separately retains
its raw canonical-field identities. Event sorting computes Python casefold and
Unicode codepoint keys before storing BLOB indexes; ties retain insertion order.
JSON formatting, XLSX column discovery/partitioning and authoritative SQLite
defaults/transactions remain unchanged. Every reader can replay all rows; reads
share one cumulative budget and original lifetime.

Version 1 limits apply to one owned replay store:

| Limit | Bound |
|---|---:|
| Database pages | At most 8 GiB, reduced if needed for journal allowance |
| Owned database/journal files | 16 GiB |
| Appended fact/change row reservations | 8,000,000 |
| One encoded row | 32 MiB |
| Cumulative decoded replay input | 128 GiB |
| Original lifetime | 21,600 seconds |
| SQLite cache | 8 MiB; mmap disabled |

Limits are finite failure boundaries, not truncation rules. A limit failure
raises; no rows are silently dropped, deduplicated or replaced with zero counts.
SQLite's hard page limit also reserves conservative rollback-journal overhead.
These bounds do not replace the owning job's resource/queue/quiet-window gates.

Scratch is a unique `.cdr-facts-*` directory beside the export directory, on the
same configured filesystem. On POSIX, successful cleanup opens the directory with
O_DIRECTORY/O_NOFOLLOW, verifies its original inode, then removes only validated
entries relative to that descriptor. It retains the tiny empty directory rather
than deleting a pathname that could now identify another directory. This is not
an atomic compare-and-unlink guarantee against arbitrary same-user changes
inside the private, solely owned directory.

Windows retains successful scratch because equivalent anchored deletion is not
implemented. `build_outputs` returns an explicit `replay_cleanup` receipt with
state/path/retained bytes; operators must budget and retain these diagnostics
until separately controlled cleanup. Failure retains scratch and a non-finalized
diagnostic where safe. Unknown files, links or changed directory ownership
prevent cleanup.
Operators must account for spool plus normal JSON/XLSX/final SQLite bytes and
retained failures before admitting large work; a failed scratch directory is not
an authoritative product capture or a backup.

Focused tests compare complete JSON bytes, workbook part XML, final SQLite rows,
duplicates/rollback, raw-source preservation, Unicode ordering, suppression and
repeated readers against the unchanged list implementation. Actual-scale proofs
must additionally retain exact source/input hashes, resource peaks, disk/time
measurements and complete output readback; passing fixtures is insufficient.

Remaining growth limits include one enormous product, other catalogue tables,
ingest concurrency and the legacy prior-day JSON/raw fallback when a compatible
immutable SQLite baseline is unavailable. This implementation does not claim
unbounded exports, raw-response completeness or accepted Pi deployment.
