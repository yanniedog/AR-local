"""Keep Gemini quota outages advisory while failing other review errors."""
from pathlib import Path
import os
import re
import sys


def review_status(outcome: str, report: str) -> tuple[int, str]:
    if outcome == "success":
        return 0, "Gemini review completed."
    # The pinned action writes this exact prefix when google-genai raises 429.
    # Match the error report, not incidental quota text in a successful review.
    quota_error = re.fullmatch(
        r"<!-- gemini-code-review -->\s*# Code Review by Gemini\s*"
        r"An unexpected error occurred in Client call: 429 RESOURCE_EXHAUSTED\. "
        r"\{'error': \{'code': 429,.*",
        report.strip(),
        re.DOTALL,
    )
    if outcome == "failure" and quota_error:
        return 0, (
            "Gemini review did not complete: API quota exhausted (HTTP 429). "
            "This advisory review must be retried after quota resets; "
            "product CI and the feedback gate remain required."
        )
    return 1, "Gemini review failed without a recognized quota error; inspect the action logs."


def main() -> int:
    outcome, filename = sys.argv[1:]
    try:
        report = Path(filename).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        report = ""
    code, message = review_status(outcome, report)
    level = "error" if code else "notice" if outcome == "success" else "warning"
    print(f"::{level}::{message}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as output:
            output.write(f"### Gemini review\n\n{message}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
