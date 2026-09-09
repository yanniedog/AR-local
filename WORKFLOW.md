# AR-local pull-request workflow

Use a fresh topic worktree from the repository default branch and preserve
unrelated changes. Open a draft PR against that exact default branch.

Run checks appropriate to changed paths. For PR automation changes, run:

```sh
npm run pr:automation:verify
git diff --check
```

Read substantive review threads and relevant comments, post one feedback plan,
implement valid fixes, and reply with `Implemented`, `Deferred`, or `Declined`
before resolving each thread. Review vendors are advisory; substantive findings
still need disposition. Applicable product CI and `bot-feedback-gate` must pass.

The tracked explicit closeout command is:

```sh
npm run pr:merge -- --pr <number>
```

Run it from the reviewed topic checkout. It checks the PR against the repository
default branch, promotes a draft only through this explicit CLI, and uses the
existing branch-sync and squash auto-merge path. GitHub branch protection remains
in force. `--dry-run` never promotes a draft. Do not substitute scripts from the
dirty developer checkout, use direct `gh pr merge`, or bypass protection.

Fix actionable state immediately. When only GitHub checks or merge processing
remain, park ownership and check once in a later turn; do not use watch loops.
After merge, run `npm run pr:bot-feedback-audit` and handle actual late findings
through a follow-up PR.

Pi operations and deployment require the separate controlled runbook and latest
complete recovery handoff. A repository merge does not authorize runtime
activation or satisfy natural-backup or physical-recovery acceptance.
