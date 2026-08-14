# Preservation evidence locator

`PRESERVATION_EVIDENCE_V1.json` is the portable, committed locator for the
verified off-repository preservation snapshot. It records the snapshot ID,
retention rule, verification populations, and the exact byte size and SHA-256
of every machine-readable preservation manifest.

The 25.5 GB source corpus and its detailed file inventory are intentionally not
published in this repository. An authorized operator supplies
`<AUSTRALIANRATES_PRESERVATION_ROOT>` out of band. Import tooling resolves the
committed snapshot ID below that root, verifies every listed manifest first,
then uses `preservation-file-inventory.jsonl` to re-hash all 1,932 protected
files. No CDR or network fallback is permitted.

Absence or mismatch is a hard stop. A fresh checkout is sufficient to identify
the exact snapshot and evidence digests it must request, but it is not authority
to access or reconstruct the private preservation corpus. The snapshot remains
retained until explicit user authorization; the planned object-locked offsite
copy is not yet claimed as complete.
