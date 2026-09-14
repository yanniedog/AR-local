# Reviewed historical registry checkout transport

`contracts/historical-fees/may23-reviewed-registry-v1.json` has one canonical
reviewed identity: 2,643 bytes with a terminal LF, SHA-256
`78906ab97dbd3cfa6d64cc0835d180015be1538ddfae44fbace9e1b296fbd314`.

Git's `-text` attribute preserves that representation in fresh checkouts. An
existing `core.autocrlf=true` checkout can retain its unchanged 2,644-byte CRLF
copy when pulling the attribute change. Git does not necessarily rewrite an
unchanged blob solely because its attributes changed.

The registry reader also recognizes exactly that former checkout representation,
SHA-256 `44071664c6ab6867cde45821a5f7c87f2e4ce343d42b4203321b5308390eee58`.
It authenticates the complete raw bytes and length before adapting the single
terminal CRLF in memory, then checks the original canonical hash and parser.
No other whitespace, JSON spelling, content, version or line-ending variation
is accepted. The checkout itself is never modified.

Raw read sizes and file-identity receipts remain bound to the actual on-disk
bytes. Both the raw and adapted checksum passes consume the shared control
meter during execution. Plans and ledger grants retain the canonical
`registry_sha256` and work identity; the CRLF digest is only a transport identity
and cannot be substituted into a plan. Source/archive fingerprints are unchanged.

The changed reader remains in the plan's exact code allowlist: existing approved
code hashes are not silently upgraded. This compatibility change authorizes no
new source read, replay, attempt, budget, claim or runtime activation, and does
not replenish previously consumed work.

The focused regression uses a disposable Git repository to reproduce a parent
checkout transitioning to the `-text` commit. Other tests verify canonical
identity, raw-byte metering and rejection of altered representations. No banking
source archive or operational ledger is opened by those transport tests.
