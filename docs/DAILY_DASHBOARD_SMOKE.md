# Dashboard verification after ingest

The daily and forced-ingest services verify all three compact history endpoints
after restarting the dashboard. They retain current-date, nonempty-bank-rate,
page, asset and current-data checks. A compact-history error still fails the
service. The three history requests allow at most 90 seconds each for headers;
other requests retain their 30-second deadline and the service keeps its existing
whole-operation limit.

This avoids populating the server's large raw-history response cache after every
restart. Compact aggregation still reads retained history and uses temporary
memory; it is not a metadata-only check or a claim of zero history work.

Ordinary `verify_local.py` and deployment acceptance keep raw history as their
default. The opt-in `--history-mode=compact` is reported in the completion message
so a routine restart result cannot be mistaken for raw-history acceptance.
Full historical coverage, source integrity and comparison semantics remain the
responsibility of the separate CDR audit and controlled deployment checks.
