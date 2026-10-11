"""Render queue overrides for the verified installed repository; no activation."""
from __future__ import annotations

import argparse
from pathlib import Path
import re


def render(template: str, repo: Path) -> str:
    value = str(repo)
    if (not repo.is_absolute() or '..' in repo.parts
            or not re.fullmatch(r'/[A-Za-z0-9_./-]+', value)):
        raise ValueError('repository root cannot be represented safely in systemd')
    result = template.replace('{{AR_LOCAL_REPO}}', value)
    if '{{' in result or '}}' in result:
        raise ValueError('unresolved service template')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(render(args.template.read_text(), args.repo_root))


if __name__ == '__main__':
    main()
