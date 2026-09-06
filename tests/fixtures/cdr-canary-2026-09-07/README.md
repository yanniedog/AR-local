# September 7 canary compatibility evidence

These nine files are complete decoded HTTP 200 response bodies retained by the
isolated `resilience-20260907` Pi canary for run date `2026-09-07`. They were copied
from its finalized attempt evidence; no production data was modified. The index
filenames retain their attempt event identifiers. `provenance.json` records SHA-256
for the exact copied bodies; Git line-ending conversion is disabled for this folder.

- Border Bank, Police Bank and Greater Bank serialize an irrelevant optional
  `depositRates` or `lendingRates` section as `null`, alongside valid numeric rates
  in the applicable section.
- Credit Union SA returns 48 index entries over three pages, matching its declared
  `totalRecords=48`; one identical repeated entry leaves 47 distinct product IDs.
- Defence Bank returns 52 entries over three pages, matching `totalRecords=52`;
  three identical repeated entries leave 49 distinct product IDs.

All four repeated entries match structurally. Raw entry counts and unique product
counts are different measurements and must both remain visible. Capturing every
returned page does not independently establish the holder's full unique product
population. Tests replay these bodies unchanged except where a test explicitly
injects a conflict, malformed field, same-page repetition or truncated page chain.
