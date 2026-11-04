#!/bin/bash
# Install day-archive spool, env, and timer/service. Does not start timers
# unless --enable is passed. Does not lift the Drive write hold.
set -euo pipefail

ROOT="${1:-/srv/ar-local/AR-local}"
ENABLE=0
if [[ "${2:-}" == "--enable" ]]; then
  ENABLE=1
fi

run_user="${AR_LOCAL_USER:-pi}"
run_group="${AR_LOCAL_GROUP:-$run_user}"
SPOOL=/var/lib/ar-local-day-archives

# Spool parent stays root-owned so the app account cannot replace children with
# symlinks that privileged install -d/chown would follow into /etc (etc.).
install -d -m 0755 -o root -g root "$SPOOL"

ensure_spool_child() {
  local child="$1"
  local path="$SPOOL/$child"
  if [[ -L "$path" ]]; then
    echo "refusing day-archive spool symlink: $path" >&2
    exit 1
  fi
  if [[ -e "$path" && ! -d "$path" ]]; then
    echo "refusing non-directory day-archive spool path: $path" >&2
    exit 1
  fi
  # Create without following links; then chown only the real directory inode.
  install -d -m 0775 "$path"
  if [[ -L "$path" ]]; then
    echo "refusing day-archive spool symlink after create: $path" >&2
    exit 1
  fi
  chown -h "$run_user:$run_group" "$path"
  chmod 0775 "$path"
}

# Ingest and the day-archive oneshot both run as the application account.
ensure_spool_child requests
ensure_spool_child work
ensure_spool_child verify
ensure_spool_child locks
# Progress/latest live under meta/ so the root-owned spool parent need not be writable.
ensure_spool_child meta
# Parent remains root:root 0755 — do not chown -R the spool.
# Migrate legacy root progress files into meta/ once (no-clobber).
if [[ -f "$SPOOL/progress.jsonl" && ! -e "$SPOOL/meta/progress.jsonl" ]]; then
  if [[ -L "$SPOOL/progress.jsonl" ]]; then
    echo "refusing legacy progress symlink: $SPOOL/progress.jsonl" >&2
    exit 1
  fi
  mv -n -- "$SPOOL/progress.jsonl" "$SPOOL/meta/progress.jsonl"
fi
if [[ -f "$SPOOL/latest.json" && ! -e "$SPOOL/meta/latest.json" ]]; then
  if [[ -L "$SPOOL/latest.json" ]]; then
    echo "refusing legacy latest symlink: $SPOOL/latest.json" >&2
    exit 1
  fi
  mv -n -- "$SPOOL/latest.json" "$SPOOL/meta/latest.json"
fi
chown -h "$run_user:$run_group" "$SPOOL/meta/progress.jsonl" "$SPOOL/meta/latest.json" 2>/dev/null || true
# raw-progress.jsonl is the daily-cdr-raw-records ledger. Do not copy
# progress.jsonl into it: those PASS rows are the immutable export-only series.
chown -h "$run_user:$run_group" "$SPOOL/meta/raw-progress.jsonl" "$SPOOL/meta/raw-latest.json" 2>/dev/null || true

# System python used by ar-local-daily / day-archive oneshot needs zstandard.
if ! /usr/bin/python3 -c 'import zstandard' 2>/dev/null; then
  /usr/bin/python3 -m pip install --break-system-packages 'zstandard==0.25.0'
fi

if [[ ! -f /etc/ar-local/day-archive.env ]]; then
  install -d -m 0755 /etc/ar-local
  install -m 0644 "$ROOT/deploy/pi/day-archive.env.example" /etc/ar-local/day-archive.env
elif [[ -L /etc/ar-local/day-archive.env ]]; then
  echo "refusing day-archive env symlink: /etc/ar-local/day-archive.env" >&2
  exit 1
else
  # Move a legacy daily-cdr-day-archives remote onto daily-cdr-raw-records.
  # Inline stdlib only: do not import the checkout. It is writable by the
  # application account, a same-named module in the caller's directory could
  # shadow it, and an older tree has no migrate_day_archive_env. -I -S ignores
  # the process environment path, user site, and the caller's directory.
  # The transport still refuses uploads into the immutable legacy folder.
  /usr/bin/python3 -I -S - /etc/ar-local/day-archive.env << 'PY'
import re
import sys
from pathlib import Path

LEGACY = "daily-cdr-day-archives"
FOLDER = "daily-cdr-raw-records"


def resolve_remote(remote):
    match = re.fullmatch(r"([a-zA-Z0-9_-]+):(.*)", remote.strip())
    if not match:
        raise ValueError("rclone remote must be name:path")
    remote_name, remote_path = match.group(1), match.group(2).strip("/")
    segments = [segment for segment in remote_path.split("/") if segment]
    if any(segment in (".", "..") for segment in segments):
        raise ValueError("day-archive remote path must not contain . or ..")
    if LEGACY in segments:
        raise ValueError(
            "refusing immutable export-only folder daily-cdr-day-archives; "
            "raw records use daily-cdr-raw-records"
        )
    if FOLDER in segments and segments[-1] != FOLDER:
        raise ValueError("daily-cdr-raw-records must be the final remote path segment")
    if not segments or segments[-1] != FOLDER:
        segments = [*segments, FOLDER]
    return f"{remote_name}:{'/'.join(segments)}"


def migrate(text):
    lines = text.splitlines(True)
    seen = False
    rewritten = []
    for line in lines:
        if not line.startswith("AR_LOCAL_DAY_ARCHIVE_REMOTE="):
            rewritten.append(line)
            continue
        seen = True
        newline = "\n" if line.endswith("\n") else ""
        raw = line[:-1] if newline else line
        key, separator, value = raw.partition("=")
        if separator != "=":
            raise ValueError("AR_LOCAL_DAY_ARCHIVE_REMOTE must be name:path")
        quote = ""
        body = value.strip()
        if len(body) >= 2 and body[0] == body[-1] and body[0] in "\"'":
            quote = body[0]
            body = body[1:-1]
        match = re.fullmatch(r"([a-zA-Z0-9_-]+):(.*)", body.strip())
        if not match:
            raise ValueError("AR_LOCAL_DAY_ARCHIVE_REMOTE must be name:path")
        remote_name, remote_path = match.group(1), match.group(2).strip("/")
        segments = [segment for segment in remote_path.split("/") if segment]
        if not segments:
            raise ValueError("AR_LOCAL_DAY_ARCHIVE_REMOTE needs a folder path")
        if segments[-1] == LEGACY:
            segments[-1] = FOLDER
        elif segments[-1] != FOLDER:
            raise ValueError(
                "AR_LOCAL_DAY_ARCHIVE_REMOTE must end in daily-cdr-raw-records "
                "or daily-cdr-day-archives"
            )
        migrated = resolve_remote(f"{remote_name}:{'/'.join(segments)}")
        rewritten.append(f"{key}={quote}{migrated}{quote}{newline}")
    if not seen:
        raise ValueError("AR_LOCAL_DAY_ARCHIVE_REMOTE missing")
    return "".join(rewritten)


path = Path(sys.argv[1])
current = path.read_text(encoding="utf-8")
updated = migrate(current)
if updated != current:
    path.write_text(updated, encoding="utf-8")
    print("migrated AR_LOCAL_DAY_ARCHIVE_REMOTE to daily-cdr-raw-records")
PY
fi

rendered=$(mktemp)
trap 'rm -f -- "$rendered"' EXIT
for unit in ar-local-day-archive.service ar-local-day-archive.timer; do
  sed -e "s|{{AR_LOCAL_REPO}}|$ROOT|g" \
      -e "s|{{AR_LOCAL_USER}}|$run_user|g" \
      -e "s|{{AR_LOCAL_GROUP}}|$run_group|g" \
      "$ROOT/deploy/pi/$unit" > "$rendered"
  install -m 0644 -o root -g root "$rendered" "/etc/systemd/system/$unit"
done
systemctl daemon-reload

if [[ "$ENABLE" -eq 1 ]]; then
  systemctl enable --now ar-local-day-archive.timer
  systemctl list-timers ar-local-day-archive.timer --no-pager
fi

echo "day-archive install complete (enable=$ENABLE user=$run_user)"
