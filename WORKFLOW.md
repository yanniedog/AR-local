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
4. Use single-shot reads:

   ```sh
   npm run pr:gates:check -- --pr <n>
   npm run wait-for-bots -- --pr <n>
   npm run pr:bot-feedback-check -- --pr <n>
   ```

   `wait-for-bots` now means required-CI settlement; reviewer presence defaults
   to off.
5. Read all review threads and relevant top-level comments before replying. Post
   one `## Feedback plan`, implement valid fixes together, then reply in-thread
   with a disposition and resolve each thread.
6. Re-run the single-shot gate audit after each fix push. Do not use agent
   `--watch`, sleep, or polling loops. If only GitHub-owned work remains, keep
   ownership parked and re-check on a later turn.
7. Enable squash auto-merge only when the PR targets `main`, actionable work is
   complete, required checks are green, and feedback closure passes.
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
