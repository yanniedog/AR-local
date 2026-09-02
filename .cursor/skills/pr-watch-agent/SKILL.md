---
name: pr-watch-agent
description: Close one bounded open-PR cycle, then verify deployment drift.
---

# PR watch agent

Process open PRs oldest first. For each PR, run the repository wait, feedback,
thread-closure, and aggregate gate commands from `WORKFLOW.md`. Fix actionable
failures on that PR's branch and use guarded squash merge only when all gates
pass. When only GitHub-owned work remains, park rather than polling.

After a merge, run read-only Pi drift verification. Deployment still requires
explicit authority and a passing backup gate.
