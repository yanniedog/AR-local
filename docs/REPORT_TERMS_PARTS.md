# Multipart private terms evidence

Use `python -m cdr_report_terms_parts --bundle <verified-bundle> --store <private-store> --output <new-directory>`
when the selected edition exceeds the single-file evidence budgets. `--technical`
only downgrades provenance. This command does not publish or approve evidence.

Each part contains at most 32 products and uses the existing sealed v1 evidence
contract, 24 MiB row/output limits, 100,000 row limit, 10 million SQLite
instruction limit, and 512 MiB processed-I/O limit. One read-only SQLite
transaction covers all parts. Retained blobs are streamed in 64 KiB chunks;
successful hashes may be reused within that export if the file identity, size,
modification time and change time match. No document bodies are cached. The
verification cache admits at most 20,000 identities. Receipts count actual I/O,
including capture/contract reads, rather than logical references to shared blobs.

Aggregate limits are 625 parts, 20,000 products, 256 MiB evidence output,
512 MiB database row bytes, one million rows, 2 GiB processed blob I/O, and
100 million SQLite instructions. A product or part exceeding a guard fails;
there is no truncation or automatic increase. The index is limited to 4 MiB.

`parts.json` binds every sealed part to the same original edition, lists ordered
product keys and resource receipts, and records the exporter hash. Before atomic
admission, `verify_parts(root, binding, keys)` independently validates every
part's seal and closed row contract, checks the exact complete product sequence,
and enforces aggregate budgets. Missing, duplicate, reordered, corrupt or
mismatched parts fail. Any failure leaves no final output directory.

Unknown document completeness and bank acceptance remain unknown. A hash seal
establishes integrity, not bank authority or authenticity. This is an evidence
transport artifact; the existing single-file HTML/CSV report consumer does not
yet accept multipart input. Full report rendering, financial reconstruction,
CI, publication and runtime acceptance are separate gates.
