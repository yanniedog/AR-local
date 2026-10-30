"""Render the dedicated archive units for review; never install or enable them."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path, PurePosixPath
import re

UNIT_NAMES = ("ar-local-payload-daily-archive.service", "ar-local-payload-daily-archive.timer")


def render(template: str, *, repo: str, data: str, portable: str, home: str,
           user: str, group: str, since: str) -> str:
    values = {"AR_LOCAL_REPO": repo, "AR_LOCAL_DATA_ROOT": data,
              "AR_LOCAL_PORTABLE_ROOT": portable, "AR_LOCAL_HOME": home}
    for value in values.values():
        path = PurePosixPath(value)
        if (not re.fullmatch(r"/[A-Za-z0-9_./-]+", value) or ".." in path.parts
                or str(path) != value):
            raise ValueError("unit paths must be canonical safe absolute POSIX paths")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", value) or value == "root"
           for value in (user, group)):
        raise ValueError("archive service requires a named non-root user and group")
    if date.fromisoformat(since).isoformat() != since:
        raise ValueError("archive start date must be YYYY-MM-DD")
    values.update(AR_LOCAL_USER=user, AR_LOCAL_GROUP=group, AR_LOCAL_ARCHIVE_START_DATE=since)
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    if "{{" in template or "}}" in template:
        raise ValueError("unresolved archive unit template")
    return template


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Exact reviewed source checkout on the Pi")
    parser.add_argument("--data", required=True)
    parser.add_argument("--portable", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    values = vars(args).copy()
    output = values.pop("output")
    source = Path(__file__).resolve().parent / "deploy/pi"
    rendered = {name: render((source / name).read_text(encoding="utf-8"), **values)
                for name in UNIT_NAMES}
    output.mkdir(parents=True, exist_ok=True)
    for name, body in rendered.items():
        path = output / name
        if path.exists():
            if path.is_symlink() or path.read_bytes() != body.encode():
                raise ValueError("existing rendered unit differs")
        else:
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
