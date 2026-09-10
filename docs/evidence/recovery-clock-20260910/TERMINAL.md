# D026 terminal result

The manually requested September 10 backup finished at 10:09:51 Hobart:
the native scheduled receipt, private-tool guard and all three component
restore checks passed. Task Scheduler reported Ready and exit code 0.
The exact installed receiver remains b6c5a4d8984ad2d2509514418c753cd555b0144f
with configuration 4a6a4f096236cc3ab4b313e1f90bfd9159f9c9a9b2a615113a85561da5e381d5.
No Windows elevation was requested. The next unchanged daily trigger is
September 11 at 06:00; this manual result is not natural-trigger proof.

`terminal-summary.json` records the actual terminal, catalog 152 and component
receipts 150–152. The content-addressed ZIP contains 240 frozen evidence files
plus the capture manifest. Archive payloads remain in the local backup target;
the receiver's actual extraction, hashes and database checks are recorded in
the receipts. `binding-current/receipt-binding.json` independently verifies
the frozen metadata against explicit production, receiver, operator, date,
catalog and component expectations. That separate verifier does not re-extract
archives or establish physical recovery.

The initial metadata-verifier invocation in `binding/` failed because its
expectations path was relative. The helper now resolves that path; the corrected
invocation passed at 10:18:04. Both invocations are preserved. This operator
invocation error did not change the completed backup or its receipts.

The preceding running snapshot, rejected v6 transaction, v5 aggregate failure
and D025 successful predecessor remain immutable. The complete terminal handoff
supersedes their current-state instructions without rewriting their outcomes.
Source PR670 passed full Linux and Windows CI. Today's public app payloads and
live Pi dashboard have passed their separately timestamped checks; the user's
specific app screen, displayed date and refresh error remain unverified.

A3 automatic-run acceptance, A4 physical boot/return safeguards and PR607
simplification acceptance remain open. This evidence-only closeout does not
deploy a different receiver or alter the Pi.
