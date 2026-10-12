# Daily repair boundary

The ingest watchdog is observation-only. Its timer calls `pi_ingest_observe.py`,
which reads capture/publication status and cannot call recovery or publication.
Normal `ar-local-daily.service` and unrelated health timers are unchanged.

The sole daily Codex controller may call
`sudo systemctl start --wait ar-local-queue-task-daily-repair.service` once at
20:00 Australia/Hobart. There is deliberately no repair timer or install target.
Do not call the former repair-capable watchdog command from a timer.

Before any repair, the service verifies its own cgroup, MainPID, restart policy,
and systemd timeouts, then exclusively creates a permanent Hobart-date claim in
`/var/lib/ar-local-daily-repair/`. A crash, failed admission, timeout, or failed
repair consumes that date. Do not delete a claim or retry after an ambiguous
response. Existing shared-Pi admission and producer locking still apply.

The kernel limits startup to 61 seconds, execution to 1100 seconds and stop
grace to 10 seconds, with another 10 seconds reserved for the stop hook. The repair process tree is
forcibly killed at its deadline, including descendants that ignore TERM or start new sessions.
The total service budget is at most 1181 seconds. Serving restoration is a separate guarded stop hook after repair has ended.
This bounds Pi repair processes; it is not a Codex token or chat-time quota.

The worker makes one pass over verified current-day evidence. Historical or
ambiguous publication queues, missing verified capture, active normal ingest,
and safety failures block repair. No blind complete re-ingest, historical
backfill, Drive queue, new schedules, or forced lock cleanup is authorized.
The claim, result and final systemd outcome retain independent evidence.

`pi-ingest-notification-test` is a manual-only, non-AI workflow. It verifies the
existing Pi issue creator and canonical marker before posting one labelled test
mention. Record the workflow/comment ID before checking Gmail. Verify automatic
Inbox delivery before any label promotion; never treat manual promotion as proof
of server-side routing.

Installation also replaces the late watchdog override and boot observation entry point. The legacy user watchdog installer now uses observation only; the commissioned duplicate user timer is disabled. Standard installers install the manual repair service without enabling it. The daily claim directory is fsynced before admission. The repair-only queue adapter retains this invocation through the existing guarded stop hook without modifying the shared queue or unrelated health services. Observations follow the scheduled due date and the existing 30/90-minute capture/publication grace periods; historical baseline gaps are not daily failures.
