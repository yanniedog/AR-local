# A4 preparation evidence addendum, September 8

This closes late PR648/PR649 preparation findings. It is append-only and does
not change prior evidence, installed software, media or recovery acceptance.

## Watchdog evidence byte representations

PR648 recorded the original 1,794-byte Windows working copy's SHA-256. Git stored
the equivalent LF representation. The JSON content is identical, but the byte
identities differ. The previous digest must not be used to validate the Git
blob. Both actual representations are now preserved in the
[byte-variants packet](evidence/a4-preparation-closeout-20260908/watchdog-byte-variants.zip),
2,409 bytes, SHA-256
`e912a3e94b6211ac26effb070d9da28f034a50e0862cb4528c9dc4a706236c7e`.

| Representation | Bytes | SHA-256 |
| --- | --- | --- |
| Original CRLF working bytes | 1,794 | `5ce83fd99d41222c7b60118de6dbf231d315bcf2ed04b29b5cf34ac9ff301b13` |
| Exact PR648 Git blob, LF | 1,769 | `75b16ec24182f8feade39ef8ee11b9d5bada90c7bc69eb38a3f925da95ce73e4` |

The packet manifest names both files, their byte counts and hashes, and source
commit `46eb380af4979a7078de3962f695a87d48850061`. Both entries were reopened and
hashed; replacing CRLF with LF in the original exactly equals the committed
blob. The original readiness document itself has identical working/Git bytes:
5,922 bytes, SHA-256
`04f87009bec3525715cf99649f6a76153f6011ba66b4f2d474730fb4773c30c0`.
No new live watchdog observation is claimed.

## Clone isolation declaration

The [draft declaration](evidence/a4-preparation-closeout-20260908/clone-isolation-draft.json)
is explicitly `INCOMPLETE`, with `physical_actions_enabled=false` and no approved
path writes. It records all ten timers actually found in the retained SD
inspection, their service counterparts and four additional known writer or
credential-bearing services: 24 required masks. This includes both
`apt-daily.timer`/`apt-daily-upgrade.timer` and their services, plus dpkg backup,
filesystem scrub, trim, log rotation and manual-page maintenance. The list is
not an assertion that the entire activation graph has been audited: unknown
units, credentials and dependencies must still fail closed before execution.

Image identity is separate from media UUID/serial. The declaration explicitly
binds the 31,902,400,512-byte May 21 historical candidate to SHA-256
`d0caeeb3a83a50b79703dd650c8198b9a0afcbbb09c667b24b716fada716be4f`.
It separately binds the same-sized original SD preservation baseline to
`ce0bcd6f1cb4364df2b97fb6324d0871a053fed6ed7738dcb0a65ef174d371d2`,
and its compressed preservation copy to its own size/hash. These have distinct
roles and must not be substituted for each other.

Before a future transaction, verify the full chosen input byte count/hash and
reject short, quarantined or corrupted inputs even if UUID/serial agree. After
approved offline restoration/isolation, bind the prepared output and physical
readback to their own full size/hash and media identity. Those output fields
remain unset, as do early-boot, kernel, OS-watchdog and deadline-return controls.
This declaration does not implement or satisfy the physical verifier.

## Receipt snapshot consistency

The receipt reader now rechecks the scheduled record and all three component
receipts after interpretation, in addition to the catalog and latest pointer.
Tests inject a concurrent edit to each referenced record without changing the
catalog/pointer and require rejection. This is a bounded read consistency check,
not a lock or promise that files cannot change after the reader returns.

The actual scheduled schema stores its observation date at
`detail.after.observation.observation_date` (or
`detail.observation.observation_date` for an unchanged-data action). It has no
top-level observation date. The existing component check compares that date,
the receipt date and the requested current Hobart date; a new negative case
confirms a stale scheduler component date is rejected. Requiring a nonexistent
top-level field would reject every retained valid scheduled record.

The risk addressed here is accepting the wrong byte representation, an
under-specified clone input/writer list or concurrently changed receipt metadata.
Controls are preserved literal bytes, separate full-image identities, an
incomplete non-executable declaration and negative tests. A3 and A4 acceptance
still require their actual current natural-run and physical boot/return evidence.
