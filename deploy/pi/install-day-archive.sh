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

# System python used by ar-local-daily / day-archive oneshot needs zstandard.
if ! /usr/bin/python3 -c 'import zstandard' 2>/dev/null; then
  /usr/bin/python3 -m pip install --break-system-packages 'zstandard==0.25.0'
fi

if [[ ! -f /etc/ar-local/day-archive.env ]]; then
  install -d -m 0755 /etc/ar-local
  install -m 0644 "$ROOT/deploy/pi/day-archive.env.example" /etc/ar-local/day-archive.env
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
