# AR-local pull-request workflow

This workflow covers repository delivery only. Pi deployment and runtime
verification remain separate post-merge responsibilities and must use the
existing blessed commands.

## Merge policy

- `bot-feedback-gate` is the only universal required check.
- Product CI remains path-filtered. A PR must pass every applicable check that
  GitHub reports, but no synthetic always-on product-CI context is introduced.
- Gemini, Codex, Sourcery, CodeRabbit, Qwen/local LLM, and reviewer-presence
  checks are advisory. Vendor quota, silence, outage, or an offline local runner
  never blocks merge.
- Every substantive finding that does arrive must receive an explicit
  `Implemented`, `Deferred`, or `Declined` in-thread disposition and GitHub
  resolution.
- The feedback workflow has one PR-scoped concurrency owner and serializes event
  bursts without cancelling duplicate required contexts. Each run is
  single-shot with a five-minute ceiling, and stale events for closed PRs exit
  cleanly instead of holding a runner.
- Squash auto-merge and branch deletion are the repository defaults.

## Delivery sequence

1. Start from current `origin/main` on a unique topic branch. Preserve unrelated
   work and use a linked worktree when the main checkout is dirty.
2. Run verification appropriate to the changed paths. Gate-automation changes
   must run:

   ```sh
   npm run pr:automation:verify
   git diff --check
   ```

3. Push and open a **draft** PR against `main`. State the agent role in the PR
   body. Do not stack a PR onto another feature branch.
4. Run the canonical single-shot helper:

   ```sh
   npm run pr:arm-and-park -- --pr <n>
   ```

   It verifies the PR targets the repository's exact default branch, explicitly
   promotes a draft, syncs when behind, arms squash auto-merge, and classifies
   the current state. The guarded `pr:merge` wrapper is the only other command
   that may promote a draft. Background queue/watch/update helpers leave drafts
   unpublished. A non-default base exits 3 as `base-unprotected`.

   - Exit 0: gates are ready, or the PR merged while auto-merge was being armed.
   - Exit 2: pending-only state; park and re-run once later.
   - Exit 3: actionable CI, conflict, unexpected closure, or feedback work.

   `pr:gates:check`, `wait-for-bots`, and `pr:bot-feedback-check` remain
   diagnostic commands. `wait-for-bots` means exact-current-head required-CI
   settlement from live protection/rules; reviewer presence defaults to off.
   Missing contexts stay pending. `pr:bot-feedback-check` distinguishes open
   feedback (exit 3) from a hard execution error (exit 1); the workflow reports
   either result in one run and relies on the next PR-head event to re-evaluate.
5. Read all review threads and relevant top-level comments before replying. Post
   one `## Feedback plan`, implement valid fixes together, then reply in-thread
   with a disposition and resolve each thread.
6. Re-run `pr:arm-and-park` after each fix push. Do not use agent
   `--watch`, sleep, or polling loops. If only GitHub-owned work remains, keep
   ownership parked and re-check on a later turn.
7. `pr:arm-and-park` owns squash auto-merge. Do not hand-roll `gh pr merge`.
   The guarded legacy `pr:merge` wrapper also refuses a non-default base.
8. After merge, run `npm run pr:bot-feedback-audit`. Late substantive review
   feedback requires a follow-up PR.
9. For product/Pi changes, complete the existing post-merge deploy and
   `npm run verify:local` / `npm run verify:pi` acceptance flow. Review-policy
   changes do not authorize Pi access or runtime mutation.

## Generated and exempt pull requests

AR-local's repository-specific exemption policy remains in
`scripts/lib/pr-gate-exempt.mjs`. Bot-authored PRs, exact generated report/mobile
release changes, and configured chore PRs may skip reviewer/thread automation;
applicable CI and branch rules still apply.
