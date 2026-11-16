# Pi lean refactor — execution handoff

Measured 2026-11-16 on `pi5` (ssh alias `ar-local-pi5`). Author: planning
session. Executor: any agent. Follow this file literally and in order. Where
this file and your own judgement disagree, this file wins; where this file is
silent, STOP (rule R1).

Goal: lean Pi disk now, lean growth forward, lean Google Drive, fewer tokens to
maintain the repo — with **no change to ingest, exports, dashboard, payload
publication or backups**, and no irretrievable data loss.

---

## 0. Rules (apply to every task)

- **R1 STOP rule.** If a command prints anything this file does not list as an
  expected result, or you are unsure which rule applies: run nothing further,
  change nothing, and report using the template in section 8. Never improvise,
  never "fix" an unexpected result, never retry with different flags.
- **R2 No pattern deletes.** Never type `rm`, `find -delete`, `git clean`,
  `truncate`, `shred`, `mv` or `>` against any Pi path unless the exact command
  is printed in this file. Never use a wildcard (`*`, `?`, `[..]`) or a variable
  you built yourself in a destructive command.
- **R3 Names lie.** Directories that look like junk are live. Verified examples
  that are wired into production systemd units today:
  `/srv/ar-local/terms-evidence-20260918`,
  `/srv/ar-local/terms-auth-20260918`,
  `/srv/ar-local/private-setup-eb58756d3d56f053b5f20087e7ba523d` (holds the
  payload key), `/srv/ar-local/alert-component-3e99a6d4-20261115`,
  `/srv/ar-local/quality-candidate-4187584c-20260920`,
  `/srv/ar-local/terms-operator-r18-20260920`, and ~20 directories under
  `/srv/ar-local/canary/`. Only `scripts/pi_storage_inventory.sh` decides what
  is referenced. Never decide by name, age or size.
- **R4 Protected forever** (no task in this file touches them; neither may you):
  `/srv/ar-local/data/runs`, `/srv/ar-local/data/state`,
  `/srv/ar-local/data/runs-archive`, `/srv/ar-local/data/task-evidence`,
  `/srv/ar-local/AR-local`, `/srv/ar-local/australianrates`, `/etc/ar-local`,
  `/etc/systemd`, everything under `/usr/local`, `/var/lib/ar-local-drive-backup/credentials`,
  anything whose name contains `avalon` or `shared-pi-queue` (another project
  shares this host), and everything on Google Drive.
- **R5 Time window.** Mutating Pi commands only between 04:00 and 23:30 Pi local
  time (`date` on the Pi). Never 00:30–03:30 (natural 01:00 ingest).
- **R6 One operator.** Before any mutating Pi command, run task P0. If P0 fails,
  STOP.
- **R7 Read-only is always allowed** (`ls`, `du`, `df`, `cat`, `systemctl status`,
  the inventory script, the dedupe script without arguments).
- **R8 Google Drive write hold is in force** (`docs/DRIVE_WRITE_HOLD.md`). Never
  run any `rclone` or `restic` command that writes, deletes, moves or prunes.
  The only Drive commands allowed are the read-only ones printed in section 5.
- **R9 Repo changes** go through a PR to `main` (`gh pr create --base main`),
  full `python -m pytest tests/ -q` green, repo merge flow in `WORKFLOW.md`.
  Never `git push --force`, never rewrite history, never `git reset --hard`.
  Merging does not deploy; **do not deploy to the Pi** — deployment is the Pi
  operator's canary flow and is out of scope here.
- **R10 Do not edit, move, rename or reformat**
  `docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md` or
  `docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md`. Code and tests bind their path
  and hash (`laptop_backup_dispatcher.py`, `a3_verifier_common.py`,
  `pi_deploy_documentation.py`, `tests/test_d012_recovery_handoff.py`).
- **R11 No sudo** except where a command in this file starts with `sudo`.
- **R12 One task per session.** Finish its verification (section 6) before
  starting the next task.

---

## 1. Measured facts (2026-11-16)

Disk: one NVMe ext4 filesystem, 1.8 T total, 849 G used, 891 G free.

| Where | Size | What it is | Task |
| --- | ---: | --- | --- |
| `/srv/ar-local/data/runs` | 374 G | Irreplaceable daily evidence, 183 days | never touched (G1 is design only) |
| `/srv/ar-local/data/.daily-export-stage` | 118 G | Byte-identical leftover copies of finalized exports, 40 days | **P1** |
| `/var/lib/ar-local-drive-backup` | 153 G | 108 G `restore-hmeddep8`, 36 G `freeze-*`, 4 G `restore-vnv24r2g`, 2 G `recovery-index-*`, all dated 2026-09-13/14 | **O1** (owner) |
| `/srv/ar-local/canary` | 90 G | 301 canary operation directories; 242 unreferenced = 51 G | **P2** |
| other `/srv/ar-local/*` entries | ~75 G | ~550 test/candidate/evidence entries; 495 unreferenced = 27 G | **P2** |
| `/var/tmp/ar-local-native-restore-20261114-*` | 16.5 G | two restore proofs from the in-flight D027 work | **O2** (owner) |
| `/var/lib/ar-local-plain-backup-work` | 8.5 G | backup work dir | **O3** (owner) |
| `/var/lib/ar-local-os-backup-20261028-n7f3a1` | 8.3 G | local copy of an OS backup that is also on Drive | **O3** (owner) |
| `/srv/ar-local/data/runs-archive/.daily-raw-stage` | 5 G | raw capture stage | never touched |
| `/srv/ar-local/data/state` | 1.9 G | durable state | never touched |

Growth: 2.6 G/day in Aug–Sep. Since 2026-11-14 (expanded provider coverage) one
day's exports are ~8 G, and the stage duplicate doubles it to ~16 G/day. At
16 G/day the disk is full in ~55 days. The Pi's own capacity monitor already
reports `warning`, runway 84 days. **P1 is therefore urgent**: it frees 118 G
and, repeated per section 4, halves forward growth.

Google Drive (account quota 5.0 TiB, 1.85 TiB used, 2.2 TiB free). The entire
AR-local backup folder is **~57 GiB**: `daily-cdr-raw-records` 29.6,
`restic` 12.2, `AR-local-Pi-OS-ARlocal-backup-20261028-n7f3a1` 8.1,
`monthly-os-recovery` 5.7, `daily-cdr-day-archives` 0.9, `AR-local-CDR-full` 0.05.
AR-local is 3 % of what is used on that Drive account. The other ~1.8 TiB is
not AR-local data and is outside this handoff.

Repository: 2,345 tracked files; 438 root-level Python modules (110 k lines);
988 test files (103 k lines); 127 docs (3.3 MB, of which the append-only
recovery handoff is 3.2 MB ≈ 900 k tokens); `.git` pack 970 MB.

Pre-existing failures (not caused by this work; do not fix here):
`ar-local-capacity-monitor.service` failed (SMTP delivery error),
`ar-local-deploy-watchdog.service` failed.

---

## 2. Tools shipped with this handoff

Both are read-only by default and refuse to run on the wrong host.

- `scripts/pi_storage_inventory.sh` — prints one TSV row per directory:
  `status reasons mtime size_mb path`. `status` is `LIVE` or `UNREFERENCED`.
  It checks systemd units, `/etc`, installed helpers, symlinks, running
  processes, git worktrees, `data/state` and production code.
- `scripts/pi_export_stage_dedupe.sh` — verifies with `cmp` that each staged
  day is byte-identical to its finalized copy; deletes only with
  `--delete-verified`, only verified days, never today or yesterday.

Copy a tool to the Pi (run on the laptop, in the repo root, on `main` after the
PR that adds this file has merged):

```bash
ssh ar-local-pi5 'mkdir -p /home/pi/lean-refactor'
```

```bash
git show origin/main:scripts/pi_storage_inventory.sh | ssh ar-local-pi5 'cat > /home/pi/lean-refactor/pi_storage_inventory.sh'
```

```bash
git show origin/main:scripts/pi_export_stage_dedupe.sh | ssh ar-local-pi5 'cat > /home/pi/lean-refactor/pi_export_stage_dedupe.sh'
```

Verify the copies. The two hash lists must be identical; otherwise STOP.

```bash
git show origin/main:scripts/pi_storage_inventory.sh | sha256sum; git show origin/main:scripts/pi_export_stage_dedupe.sh | sha256sum
```

```bash
ssh ar-local-pi5 'sha256sum /home/pi/lean-refactor/pi_storage_inventory.sh /home/pi/lean-refactor/pi_export_stage_dedupe.sh'
```

---

## 3. P0 — preflight (before every mutating session)

Run on the Pi (`ssh ar-local-pi5`), one command at a time.

1. `hostname` → must print `pi5`. (A different Pi exists at 10.0.0.2; wrong
   host = STOP.)
2. `date +%H:%M` → must be between `04:00` and `23:30`.
3. `systemctl is-active ar-local-daily.service ar-local-ingest-now.service ar-local-day-archive.service`
   → every line must be `inactive` or `failed`. Any `active`/`activating` = STOP
   and try again in one hour.
4. `ls /srv/ar-local/data/state/$(date +%F).done.json` → must print the path.
   "No such file" = today's ingest has not finalized = STOP.
5. `pgrep -af 'pi_shared_queue.py run|pi_shared_task' | grep -v pgrep` → must
   print nothing. Any output = another operator's job is queued or running =
   STOP and try again in one hour.
6. `df -BG --output=avail / | tail -1` → record the number.
7. Save the baseline (read-only):
   `systemctl list-units 'ar-local*' --state=failed --no-legend --plain | awk '{print $1}' | sort > /home/pi/lean-refactor/failed-before.txt; cat /home/pi/lean-refactor/failed-before.txt`

---

## 4. P1 — remove byte-identical export-stage duplicates (frees ~118 G)

Why it is safe: each `/srv/ar-local/data/.daily-export-stage/<date>/_exports`
is the staging copy that the daily ingest already installed into
`/srv/ar-local/data/runs/<date>/…/_exports`. The tool proves byte equality of
every staged file against the finalized copy before removing anything. The
production code already treats a missing stage directory as "cleaned"
(`cdr_daily_archive_gate.py`, `if not stage.exists(): return CLEANED`) and the
backup scope lists the directory as transient
(`ar_local_backup_scope.py: TRANSIENT_EMPTY_DIRS`). On 2026-11-16 the dry run
verified these days as identical (record your own run; do not trust this list):
see section 9.

Steps (Pi, user `pi`):

1. Run P0.
2. Dry run:
   `nice -n 19 ionice -c3 bash /home/pi/lean-refactor/pi_export_stage_dedupe.sh | tee /home/pi/lean-refactor/p1-dry.txt`
   Expected: lines starting `VERIFIED` or `KEEP`, then one `SUMMARY mode=dry …`
   line. Takes 10–30 minutes. A line starting `STOP` = STOP.
3. Count check: `grep -c '^VERIFIED' /home/pi/lean-refactor/p1-dry.txt` must be
   ≥ 1, and `grep '^KEEP' /home/pi/lean-refactor/p1-dry.txt` may only show the
   reasons `too-recent`. Any other KEEP reason: continue (those days are simply
   kept) but include the KEEP lines in your report.
4. Delete verified days through the shared queue (this is the only mutating
   command of P1):
   `pi-shared-task --project ar-local --resource ar-local --mode exclusive --cpu-slots 1 --max-runtime 7200 --wait-timeout 1800 -- /bin/bash /home/pi/lean-refactor/pi_export_stage_dedupe.sh --delete-verified 2>&1 | tee /home/pi/lean-refactor/p1-delete.txt`
   Start it between 04:00 and 21:00 only (it may run up to two hours and the
   queue refuses jobs that could reach 00:30). Expected: `DELETED` and `KEEP`
   lines, then `SUMMARY mode=delete …`. If the job is cut off before the
   SUMMARY line, nothing is lost (a half-removed stage day is still a proven
   duplicate): wait one hour, run P0, run this same step again.
   If it prints `STOP: run as user pi`, the queue ran it as another user:
   STOP and report; do not use sudo, do not bypass the queue.
5. `df -BG --output=avail / | tail -1` → must be larger than the P0 number by
   roughly the `reclaim_mb` in the summary.
6. Run section 6 verification.

Repeat P1 once a month (same steps). It never deletes today or yesterday.

Cause (diagnosed 2026-11-16; owner task, not for the executor): the stage is
preserved on purpose while private terms capture is unfinished. The newest
receipt in `data/state/terms-capture-receipts/` is `CAPTURE_FAILED`, reason
`complete_terms_capture_exceeds_safe_bounds`, `raw_stage_preserved: true`.
`cdr_daily.py` only removes the export stage after the raw stage is `CLEANED`,
which needs a successful terms capture. Until the terms-capture owner fixes
that bound, every day keeps its raw stage (~0.14 G, needed for the retry —
never touch `runs-archive/.daily-raw-stage`) and its export stage (a full
duplicate, not needed for the retry — P1 removes it). An earlier theory that
the inventory-equality check in `cdr_daily_archive_gate.py` was at fault is
withdrawn; no code change is proposed here.

---

## 5. Remaining Pi and Drive tasks

### P2 — quarantine unreferenced operation directories (~27 G first round, reversible)

Quarantine means rename into `/srv/ar-local/_quarantine/`. It is on the same
filesystem, so it is instant, frees nothing, loses nothing, and is undone by
renaming back. Deletion is a separate owner step (O4).

Scope: only direct children of `/srv/ar-local` and of `/srv/ar-local/canary`.
Never `/var/lib`, `/var/tmp`, `/usr/local`.

1. Run P0.
2. First inventory:
   `sudo bash /home/pi/lean-refactor/pi_storage_inventory.sh --sizes > /home/pi/lean-refactor/inv-A.tsv`
   (10–20 minutes).
3. Wait until at least one natural 01:00 ingest has finalized after step 2
   (next day, after P0 step 4 passes). Then second inventory, same command with
   output `inv-B.tsv`.
4. Build the candidate list — a path qualifies only if it is `UNREFERENCED` in
   **both** inventories and its mtime is 2026-11-01 or earlier:
   `awk -F'\t' 'NR==FNR{if($1=="UNREFERENCED")a[$5]=1;next} $1=="UNREFERENCED" && a[$5] && $3<="2026-11-01" && $5 ~ "^/srv/ar-local/" {print $5}' /home/pi/lean-refactor/inv-A.tsv /home/pi/lean-refactor/inv-B.tsv > /home/pi/lean-refactor/p2-candidates.txt; wc -l /home/pi/lean-refactor/p2-candidates.txt`
5. Safety filter — this must print nothing; if it prints any line, STOP:
   `grep -E '^/srv/ar-local/(AR-local|data|australianrates|canary|_quarantine)$|/\.\.|[[:space:]]' /home/pi/lean-refactor/p2-candidates.txt`
6. Show the list to the owner and get a written "yes, quarantine these" in
   chat. No yes = STOP.
7. Quarantine (one queue job; creates a restore map):
   `pi-shared-task --project ar-local --resource ar-local --mode exclusive --cpu-slots 1 --max-runtime 1800 --wait-timeout 1800 -- /bin/bash -c 'set -eu; Q=/srv/ar-local/_quarantine/$(date +%Y%m%d); mkdir -p "$Q/canary"; while IFS= read -r p; do case "$p" in /srv/ar-local/canary/*) d="$Q/canary/$(basename "$p")";; *) d="$Q/$(basename "$p")";; esac; [ -e "$p" ] && [ ! -e "$d" ] || { echo "SKIP $p"; continue; }; mv -n -- "$p" "$d" && printf "%s\t%s\n" "$p" "$d" >> "$Q/RESTORE_MAP.tsv"; done < /home/pi/lean-refactor/p2-candidates.txt; wc -l "$Q/RESTORE_MAP.tsv"'`
   If `mv` reports "Permission denied" for root-owned entries, those entries
   are simply skipped; list them in the report. Do not use sudo.
8. Run section 6 verification now, and again after each of the next 14 natural
   ingests. Any new failure → run the rollback in section 7 immediately.

Entries that stay `LIVE` only because of `symlink-sibling` become candidates in
a later P2 round once the directories that link to them are gone. Repeat P2
(new inventories A and B) after O4.

### Owner-only decisions (executor: report, never act)

- **O1 `/var/lib/ar-local-drive-backup` (153 G).** `restore-hmeddep8`,
  `restore-vnv24r2g`, `freeze-20lus8c2`, `freeze-fdf83qqx`, `freeze-i653bmg6`,
  `freeze-zu8l1i4z`, `recovery-index-94rzmekz`, `recovery-index-rs4ih34b` are
  `tempfile.mkdtemp` leftovers from 2026-09-13/14, but spool receipts,
  manifests and `recovery-seeded-drive-seed-717-20260914-a.json` name them, and
  `pi_drive_backup_seed.py` can consume a `restore-XXXXXXXX` directory. Removal
  is a backup-design decision under the Drive hold.
- **O2 `/var/tmp/ar-local-native-restore-20261114-*` (16.5 G).** Belongs to the
  unfinished D027 activation (handoff checkpoint 79). Remove only after that
  activation is accepted. `/var/tmp/avalon-*` belongs to another project.
- **O3** `/var/lib/ar-local-plain-backup-work/391eacd7290a4df5b12acdb5af1fae59`
  (8.5 G) and `/var/lib/ar-local-os-backup-20261028-n7f3a1` (8.3 G; a copy
  exists on Drive, 8.1 GiB).
- **O4 Delete quarantine.** After 14 clean ingests, the owner (not the
  executor) approves and runs deletion of one dated quarantine directory by its
  literal full path.
- **O5 13 stale git worktrees** registered in the production checkout
  (`terms-candidate-*-20260919`, `terms-bounded-logs-proof-r29`,
  `publication-r67-8c5621ec-20260922`, `canary/prep-0d8cd36a478a-20261026`).
  They are `LIVE` (worktree) in the inventory; removing them is
  `git worktree remove`, a production-checkout mutation.
- **O6 Mandatory-reading rule.** `AGENTS.md` and `docs/HANDOFF.md` tell every
  agent to read the 3.2 MB recovery handoff "in full" (~900 k tokens; it does
  not fit in one context). Recommended wording: "read the runbook's safety
  invariants and the **last three checkpoints** of the handoff
  (`grep -n '^## Checkpoint' … | tail -3`)". This changes operating policy, so
  the owner must approve the exact text before any PR.

### G1 — forward growth of `data/runs` (design; no executor action)

After P1, growth is ~8 G/day ≈ 110 days of runway. One finalized day is mostly
one pretty-printed `banks-<date>.json` (1.4 G+), one `local-cdr.sqlite` (1 G+)
and one `.xlsx`. The Drive day-archives of the same days are ~15 MB compressed,
so this data compresses by well over 10×. Options for the owner, smallest
behaviour risk first:

1. Stop producing the stage duplicate (P1 permanent fix).
2. Cold-tier finalized days older than N days to `zstd` files with a recorded
   hash and a verified Drive copy, readers updated to open both. This changes
   integrity baselines and readers; it needs its own design, tests and canary.
3. Add disk.

Until one is chosen, `storage` policy in `docs/STORAGE_AND_PAYLOAD_BUDGETS.md`
stands: no retained CDR evidence is deleted.

### D1 — Google Drive (read-only measurement; no cleanup needed today)

AR-local uses ~57 GiB; Drive is not a constraint. Watch item: `monthly-os-recovery`
adds ~5.7 GiB per month and no retention limit was found; ask the owner for a
keep-N policy when it passes 12 snapshots. Quarterly measurement (read-only,
run on the Pi, exactly as printed):

```bash
sudo rclone --config /var/lib/ar-local-drive-backup/credentials/dedicated-20260913-ready3/rclone-verified-ready3.conf --tpslimit 4 size "ar_local_drive_dedicated_20260913:AR-local Pi Backups Dedicated 20260913-326040d72fbc405ea2e9b2dacea6b412"
```

Expected `Total size` below 150 GiB. Above that: report to the owner. Never run
any other rclone verb.

---

## 5b. Repository tasks (laptop; PR per task; rule R9)

### C1 — add this handoff and the two tools

Files: `docs/PI_LEAN_REFACTOR_HANDOFF.md`, `scripts/pi_storage_inventory.sh`,
`scripts/pi_export_stage_dedupe.sh`. Add one line to `.gitattributes`:
`scripts/pi_*.sh text eol=lf`. No other file.

### C2 — delete five unreferenced root scripts

Exactly these files and nothing else: `strip_bank_sprite.py`,
`verify_account_class.py`, `verify_email_notify.py`, `verify_ingest_sanity.py`,
`verify_lvr_parsing.py`. Evidence: no import, test, workflow, npm script,
systemd unit or installed Pi helper invokes them; their only mentions are two
historical file listings under `docs/evidence/git-dependency-20260910/`
(leave those listings unchanged).

For each file, immediately before deleting, this must print `0`; any other
number = skip that file and report it:

```bash
git grep -l -w -e verify_lvr_parsing -- . ':!verify_lvr_parsing.py' ':!docs/evidence' | wc -l
```

(substitute each module name in both places). Then `git rm <file>`, run
`python -m pytest tests/ -q`; any failure = `git restore --staged --worktree <file>`
and report.

### C3 — candidates the executor must NOT delete

Referenced only by their own tests (7,035 lines); several are operator
entry points installed or run by hand. Owner decides each:
`a3_backup_terminal_verify.py`, `app_payload_prepack_history.py`,
`app_payload_public_bootstrap.py`, `cdr_historical_fee_repair.py`,
`cdr_historical_taxonomy.py`, `cdr_ledger_replicate.py`,
`cdr_product_report_parts.py`, `cdr_run_journal.py`,
`laptop_backup_transition.py`, `laptop_backup_trusted_package.py`,
`pi_canary_acceptance_assemble.py`, `pi_canary_emulator_device_probe.py`,
`pi_canary_shadow_ingest.py`, `pi_ci_install.py`, `pi_drive_backup_enroll.py`,
`pi_drive_backup_hold_activate.py`, `pi_native_ssh.py`,
`pi_payload_archive_units.py`, `pi_plain_backup_entry.py`,
`pi_plain_backup_install.py`, `pi_plain_backup_packet.py`,
`pi_plain_backup_parent.py`, `pi_plain_backup_reclaim_wrapper.py`,
`pi_plain_backup_reconcile.py`, `preservation_evidence.py`.

### C4 — forbidden repository changes

Do not: move modules into packages or rename any `.py` file (systemd units and
installed helpers call them by absolute path); delete or edit tests or
`tests/fixtures`; delete or move anything under `docs/evidence`; move or rename
any doc that `git grep -n '<basename>' -- . ':!docs'` finds; rewrite git
history to shrink the 970 MB pack; run `git gc` on the Pi checkout; touch
`.github/workflows`. To save clone size and tokens use
`git clone --filter=blob:none` and read docs with `grep`/`tail`, not in full.

---

## 6. Verification (after every Pi task)

All read-only, on the Pi unless stated. Every line must hold; otherwise run
section 7 (if the task was P2) and STOP.

1. `systemctl is-active ar-local-dashboard.service` → `active`.
2. `curl -fsS -o /dev/null -w '%{http_code}\n' --max-time 20 http://127.0.0.1:8808/api/latest` → `200`.
3. `systemctl list-units 'ar-local*' --state=failed --no-legend --plain | awk '{print $1}' | sort | comm -13 /home/pi/lean-refactor/failed-before.txt -`
   → prints nothing (no new failed unit).
4. `ls /srv/ar-local/data/runs | wc -l` → not smaller than before the task.
5. Laptop, repo root: `npm run verify:pi` → exits 0.
6. Next day after 03:30: `ls /srv/ar-local/data/state/$(date +%F).done.json`
   → prints the path; and repeat checks 1–3.

## 7. Rollback (P2 only; P1 needs none — it removes proven duplicates)

Restore every quarantined path of one dated quarantine (replace `YYYYMMDD`
with the literal directory name shown by `ls /srv/ar-local/_quarantine`):

```bash
pi-shared-task --project ar-local --resource ar-local --mode exclusive --cpu-slots 1 --max-runtime 1800 --wait-timeout 1800 -- /bin/bash -c 'set -eu; while IFS=$(printf "\t") read -r orig q; do [ -e "$q" ] && [ ! -e "$orig" ] && mv -n -- "$q" "$orig" && echo "RESTORED $orig"; done < /srv/ar-local/_quarantine/YYYYMMDD/RESTORE_MAP.tsv'
```

Then run section 6 again and report.

## 8. Report template (use for success and for STOP)

```text
Task: <P0|P1|P2|C1|C2>
Result: <DONE|STOPPED at step N>
Exact last command and its full output:
Free space before / after (GiB):
Section 6 checks 1-5: <pass/fail each>
Anything unexpected:
```

## 9. Dry-run evidence from 2026-11-16

`pi_export_stage_dedupe.sh` (no arguments, read-only) was run on the Pi by the
planning session and ran to completion:
`SUMMARY mode=dry verified=38 kept=2 reclaim_mb=101713`. All 38 staged days
from 2026-09-19 to 2026-11-14 printed `VERIFIED`; the only `KEEP` lines were
2026-11-15 and 2026-11-16 (`too-recent`). Those two days (16 G) become eligible
on later runs. Re-run the dry run yourself; do not rely on this record.
Nothing was deleted, moved or changed on the Pi or on Google Drive during
planning; the only writes were temporary files the tools removed themselves.
