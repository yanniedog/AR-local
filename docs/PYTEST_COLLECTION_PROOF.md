# Exhaustive protected pytest evidence

The protected suite now produces `ar-local-sequential-pytest-v2` evidence.
Previously sealed v1 receipts remain verifiable; they are not rewritten or
reinterpreted as v2 runs.

V2 first asks pytest to traverse the entire `tests` root using its native
directory, configuration and ignore rules. A bound reporter intercepts module
collection before importing every test module together and records the ordered
module inventory. Discovery is not allowed to narrow its selector, follow linked
paths, ignore an error or skip an unverified directory. Unsupported global
collection hooks and nonstandard collectors fail closed. Per-module
parametrization remains native pytest behavior; global/conftest
`pytest_generate_tests` hooks are unsupported because they can carry state
between modules that disappears at a partition boundary.

Fresh child processes collect contiguous groups of at most 48 discovered modules.
The proof binds every selector, ordered node ID, parametrization, collection skip,
runtime/context and raw report. Every discovered module, including an empty
module, has an explicit visit and terminal collection outcome, and then executes
as a whole module in another child. An absent module cannot masquerade as an
empty one. Its collected nodes and
skips must exactly match the corresponding collection evidence. Every test needs
the original terminal setup/call/teardown evidence. The final XML is reconstructed
from those raw identities and phases, never accepted by test counts alone.

Discovery, all collection children and all execution children share the existing
3,600-second pytest deadline and the unchanged outer resource monitor. There is
no fresh resource baseline or admission per partition. Exact PID/start-time
ownership must return to the original supervisor set after each child. Host-swap,
source integrity, immutable fixture, rollback and deployment checks are unchanged.

The payload CI job still runs the full ordinary suite. It additionally runs
`scripts/qualify-partitioned-collection.py` with Linux Python 3.13.5, pytest 9.1.1
and the qualified Pi runtime's direct collection dependencies. The real reporter
compares native monolithic collection against discovery plus partitions by exact
ordered node records, skips and context. It rechecks source filenames, bytes and
commit and retains the raw evidence as a CI artifact. The reported architecture
is explicit: this differential qualification does not replace actual Pi canary
acceptance. `--development` always labels evidence development-only.
Both qualification modes inventory nonignored untracked files before and after;
normal CI additionally refuses an initial untracked source inventory.
CI records the post-test checkout status and qualifies a pristine detached
worktree at the identical Git commit. It preserves original test artifacts and
does not clean, ignore or admit them into the source qualification.

An unsupported collection hook, dependency/platform-specific behavior or changed
inventory must produce a failure requiring review. Do not seed Pi expectations
from a Windows node list, suppress collection errors, drop a test module or relax
the resource guard to make an operation pass.
