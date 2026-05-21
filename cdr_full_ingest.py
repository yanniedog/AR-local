#!/usr/bin/env python3
"""
Standalone Australian CDR PRD ingest for **banking** products: Mortgage, Savings, and TD.

Fetches register rows (summary + banking register fallbacks), walks each holder's
paginated product index, and saves JSON payloads to disk under a per-run layout:

  <out>/<YYYY-MM-DD>/banks/Mortgage|Savings|TD/...

Usage:
  python cdr_full_ingest.py [--out DIR] [--date YYYY-MM-DD] [--resume]
  python cdr_full_ingest.py --holders commbank --max-pages 2 --max-products 50
  python cdr_full_ingest.py --workers 16
  python cdr_outputs.py runs/2026-05-06
  python cdr_dashboard_server.py --exports runs/2026-05-06/_exports
  python cdr_daily.py --workers 8

Holders are ingested in parallel via a thread pool (default --workers 8).

Exit codes: 0 success; 1 no holders matched ``--holders`` (register OK); 2 register
failure or zero banking brands without filter waiver. Use ``--allow-empty-holders`` to
exit 0 when register discovery fails or filters match nothing.

Default run date folder uses UTC (YYYY-MM-DD). Banking layout:

  <out>/<YYYY-MM-DD>/banks/Mortgage/<Bank>/<ProductName>/<safe-id-dir>/product-detail.json
  <out>/<YYYY-MM-DD>/banks/Savings/...
  <out>/<YYYY-MM-DD>/banks/TD/...
  <out>/<YYYY-MM-DD>/banks/_holders/<Bank>/_products-index/page-0001.json

Each leaf includes ``product-id.txt`` with the canonical CDR ``productId``; the directory
name is a sanitized segment plus a short hash (Windows-safe, collision-resistant).
Failed detail GET bodies are written as ``product-detail.error.txt`` next to the leaf.

Public PRD only: no consumer consent, no Cloudflare, no Australian Rates API.

References (external standards):
  Consumer Data Standards banking PRD; ACCC CDR register.
  Register: https://api.cdr.gov.au/cdr-register/v1/
"""

from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from cdr_ingest_lib import main


if __name__ == "__main__":
    raise SystemExit(main())
