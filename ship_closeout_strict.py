#!/usr/bin/env python3
"""Exit 2 when an open PR exists for the current branch (same intent as AustralianRates ship:closeout:strict)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ship_closeout_strict: git not available or not a repo", file=sys.stderr)
        return 1
    if not branch or branch == "main":
        return 0
    try:
        out = subprocess.check_output(
            ["gh", "pr", "list", "--head", branch, "--json", "number"],
            text=True,
        )
    except FileNotFoundError:
        print("(Install gh CLI for ship closeout checks.)")
        return 0
    except subprocess.CalledProcessError:
        print("ship_closeout_strict: gh pr list failed", file=sys.stderr)
        return 1
    try:
        data = json.loads(out or "[]")
    except json.JSONDecodeError:
        print("ship_closeout_strict: invalid gh JSON", file=sys.stderr)
        return 1
    if data:
        pr_number = data[0].get("number")
        print(
            f"ship_closeout_strict: open PR still exists for {branch} — complete WORKFLOW.md steps 5–9.",
            file=sys.stderr,
        )
        if pr_number:
            try:
                gate = subprocess.run(
                    ["node", "scripts/pr-bot-feedback-check.mjs", "--pr", str(pr_number)],
                    cwd=_REPO_ROOT,
                )
            except FileNotFoundError:
                print(
                    "ship_closeout_strict: Node not found; run npm run pr:bot-feedback-check manually.",
                    file=sys.stderr,
                )
                return 2
            if gate.returncode == 1:
                print(
                    "ship_closeout_strict: bot feedback gate failed — close review threads before merge.",
                    file=sys.stderr,
                )
                return 2
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
