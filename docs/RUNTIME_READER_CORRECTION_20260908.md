# Runtime reader correction, September 8

Six late findings on PR653 are addressed without changing the installed receiver,
Windows task, production checkout or physical recovery state. Historical scripts
and readbacks remain unchanged. The earlier runtime helpers are superseded for
future use by `runtime-identity-isolated.ps1` and the source-pinned capture below.

The independent `laptop_recovery_runtime.py` uses only the standard library and
runs as a source file under `-I -S -B`. It does not import installed receiver code,
including ignored bytecode caches. Required checks use explicit exceptions, so
optimization cannot remove them. Executable and configuration pins remain checked.
Both local and remote Git status explicitly include untracked files and disable
optional locks and filesystem-monitor hooks. Local Git environment overrides are
removed before invocation. Tests use actual temporary Git repositories to verify
hidden untracked files cause failure and stale stat information does not change
the index. Optimized-Python and cache-injection tests run separate interpreters.
[Python command-line controls](https://docs.python.org/3/using/cmdline.html),
[Git status](https://git-scm.com/docs/git-status).

The receipt reader now holds the existing `.scheduled-record.mutex` through
scheduled, component, catalog and pointer validation, using the same OS locking
primitive as the terminal writer. It opens the mutex read-only, never creates it,
and fails promptly if absent, empty or busy. Frozen offline packets need an
already-preserved mutex to use this live-reader interface; the reader never
creates coordination files on the caller's behalf. Tests confirm byte/mtime
preservation and exclusion of another process through the final pointer read.
Changes after lock release still require a new read; this is not durable acceptance
of a future state, full ancestry validation, or a replacement for A3/A4 evidence.

## New execution evidence

The runtime check passed at 2026-09-08T12:25:26.7755881+10:00. The task was Ready
with exit zero, same definition, last run September 8 at 08:56:54 and next run
September 9 at 06:00. Receiver/configuration and clean production2607 were
unchanged; pinned known-hosts bytes and mtime were unchanged. This was a new
read-only observation, not a backup, restore, receiver update or physical test.

The helper and Python source were committed at
`e4e0ba2c96b4598541ed5d07203a269112688ea1` before execution. The capture driver was
committed at `d928152057d8ea37cc1865056fb8df425de28054` before execution and checks
their exact hashes before and after invocation. The actual driver invocation was:

```powershell
$capture='C:\code\AR-local-a4-isolation-0908\docs\evidence\runtime-reader-safety-20260908\capture-once.ps1'
if((Get-FileHash -LiteralPath $capture).Hash.ToLowerInvariant() -cne '9289e078a01621b04f927cfefeff30b830bfd2366ef62b2b4c626f660eaa971c'){throw 'Capture driver changed before execution.'}
& $capture -OutputDirectory 'C:\code\AR-local-a4-isolation-0908\docs\evidence\runtime-reader-safety-20260908\execution-01'
```

This is a historical exact command: do not replay it into `execution-01`. A later
approved read must use a new output directory and reviewed current runtime pins.
The capture driver records failures as well as successes and refuses existing
output directories. PowerShell output objects are joined with LF and a final LF,
then saved as UTF-8 without BOM. Embedded CRLF inside a ConvertTo-Json output
object is preserved; joining objects does not normalize those internal newlines.
This transformation is explicit in capture.json and the retained driver source.
The capture driver itself was hash-checked by the command above before execution.

| Artifact | Bytes | SHA-256 |
| --- | --- | --- |
| laptop_recovery_runtime.py | 6436 | `36e95ee5322c2485ad978bf5ca608072a4a149c535f6a08b4e953d7d4f649f67` |
| docs/evidence/runtime-reader-safety-20260908/capture-once.ps1 | 3040 | `9289e078a01621b04f927cfefeff30b830bfd2366ef62b2b4c626f660eaa971c` |
| docs/evidence/runtime-reader-safety-20260908/execution-01/capture.json | 1239 | `a86faba1c811d3ed3aab612c485c87bacf52bf3e01d7e7ed9b757b1969885fa0` |
| docs/evidence/runtime-reader-safety-20260908/execution-01/stdout.json | 4567 | `5ff2542236971cbd627f7b582f501aa0f156d2d371a02ef270d1a20992025ca6` |
| docs/evidence/runtime-reader-safety-20260908/runtime-identity-isolated.ps1 | 3348 | `6fcf4d195e5b68caa969349af6b8f081605c794ad2dbfba2e435d23ddb0c9243` |

Validation: 130 focused tests passed and one Windows symlink privilege test was
skipped; applicable full Linux and Windows CI remains required. A3 remains
RUNNING and A4 BLOCKED. The old runtime readback's pre-execution hash/capture
provenance was not retained in that entry; this new execution supplies its own
stronger provenance and does not retroactively upgrade the old result.
