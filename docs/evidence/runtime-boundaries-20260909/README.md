# September 9 runtime verification and early backup

Five late findings on PR654 are corrected by this source change: Git must resolve
the requested worktree, no index flags may hide tracked changes, all installed
backup writers must be excluded during receipt validation, a failed Python
probe must retain its structured output, and evidence parents must not traverse
Windows reparse points. The focused suite passed 139 tests with one Windows
symlink privilege skip. The junction regression ran without elevation.

Receipt verification reads existing evidence bytes without rewriting them, but
now creates and removes two temporary coordination lock files:
`user-session-lock/catalog/.receiver.lock` and `catalog/.receiver.lock`.
It also holds the existing scheduled-record mutex. Missing directories, busy
writers and missing mutexes fail closed; it neither repairs metadata nor starts
a backup. This supersedes earlier claims that receipt verification creates no
files. Only fixture tests exercised this reader during this session.

The separate runtime reader remains read-only and uses `-I -S -B`. Source
commit `74e5876941df66caf06ce489a6866b4180f09571` introduced the fixes. Driver
commit `ebcb36a61fb0e6b70c5a37e3ed2a7eddace99804` preceded the first execution.
The current-runtime helper was committed at
`cc4219308532081bdc8bea8aeedbf01121f0dca3`, and its driver at
`b7bed4e3c65e0e05f1236ff783bac8363bb05e83`, before either current-runtime probe.

| Capture | Result | What it establishes |
| --- | --- | --- |
| execution-01 | FAIL 05:24 | Yesterday's task Actions no longer match. |
| execution-current-01 | FAIL 05:26 | SSH exited 255; structured failure output was retained. |
| execution-current-02 | PASS 05:27:51 | Current task, config, receiver and clean production identity match the replacement baseline. |

Every capture includes exact helper commands, source/driver hashes and stdout
hashes. Output objects are joined with LF and a final LF, encoded as UTF-8 without
BOM; embedded CRLF inside PowerShell JSON remains intact. `.gitattributes`
preserves literal artifact bytes. Failed captures are never overwritten.

Another task installed `source-auth-publication-20260908-v4` on September 8 at
20:25. Its copied installation, predecessor verification, task XML and config
are under `receiver-transition`. The receiver code is still `cbf920e`, but the
protected production commit is now `3de4d35d1f3af8b647477bfeb327c9466f5c49f6`
and config SHA256 is
`5bdb944363ec5276ea8662f99ba4d37e3852f2049bb8fd590a8cc2f664b798ca`.
The replacement capture records this real transition; it does not retroactively
change the meaning of earlier backup or runtime proofs.

The user subsequently instructed, "Do it now rather than 6am." The ordinary-user
task invocation at 05:32 was blocked by its 06:00-14:00 application start rule.
The date-bounded `run-early-once*.py` wrappers implement that explicit one-time
scheduling exception only. They retain ordinary-token, config, runtime, transport,
whole-job and component locks, receiver preflight and quiet-window checks. They
change no installed source, configuration, scheduled task or operating-system
privileges. Each has a create-once authority record. The first wrapper's isolated
interpreter could not load the installed user-site jsonschema dependency; later
attempts use the installed launcher's normal `-B` interpreter mode. These are
backup execution wrappers, not the isolated read-only runtime observer.

At 05:34-05:37, public rolling v1/v2, dates-index and the dated September 9
manifest all reported September 9. Both core downloads matched their manifest
SHA256. Core sections contain 7,996 mortgage, 2,077 savings and 6,226 term-deposit
rows. The Pi daily service started at 01:00:05, its main process exited zero at
01:17:15, and its journal recorded successful dashboard verification and service
completion at 01:19:07. No ingest was manually rerun. No phone was connected, so
the user's displayed date and device refresh failure remain unverified.

A manually started backup cannot establish a natural task trigger. A3 remains
RUNNING, A4 remains BLOCKED, and PR607 remains draft until their separate
acceptance criteria are met. No media, firmware, boot, restart or deployment
action is part of this change.
