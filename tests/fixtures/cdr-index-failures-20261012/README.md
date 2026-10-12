# Retained public CDR responses

These are the exact HTTP response bytes from the finalized observation
`obs-2026-10-12-f852127ddfd822fc`, retained without new provider requests.
They contain public product data and public API errors, not credentials.

| File | Provider / HTTP status | Bytes | SHA-256 |
| --- | --- | --- | --- |
| geelong-index.json | Geelong Bank / 200 | 18682 | 22d9b04e4ffca25f1850478209789944ea4e067fe384854f6c3775f1a9689a68 |
| ddh-index-error.json | DDH Graham / 401 | 211 | fc6cd986fbef03494dfbd487f1ac228403b57526de4f8dd27395f0f8decd63f5 |

The Geelong response completed at `2026-10-11T14:05:24.681605Z`; its
journal event is `00001590-82e967d6108e98bb.json`. It has 18 rows, of which
17 have product identities. The final row has an empty identity.
The public endpoint is
`https://online.geelongbank.com.au/OpenBanking/cds-au/v1/banking/products`.

The DDH response completed at `2026-10-11T14:05:13.789072Z`; its journal
event is `00001152-fcbae7e4a9ab0802.json`. It reports a server-side failure
fetching the tenant's authorization token.
The public endpoint is
`https://api.cds.ddhgraham.com.au/cds-au/v1/banking/products`.

Tests replay these bytes at HTTP boundaries. Protocol mutations and control
counters in tests do not constitute live capture or financial acceptance.
