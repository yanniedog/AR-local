#!/usr/bin/env bash
# READ-ONLY Pi storage inventory. Writes nothing outside its own mktemp dir.
# Classifies every direct child of the scan roots as LIVE (referenced by a
# running process, systemd unit, config file, installed helper, symlink, git
# worktree registration or the data/state tree) or UNREFERENCED.
# UNREFERENCED means "no reference found", NOT "safe to delete". See
# docs/PI_LEAN_REFACTOR_HANDOFF.md for the only permitted next step.
# Usage on the Pi:  sudo bash pi_storage_inventory.sh [--sizes]
set -u
export LC_ALL=C
[ "$(hostname)" = pi5 ] || { echo "STOP: wrong host $(hostname)"; exit 2; }
SIZES=0; [ "${1:-}" = "--sizes" ] && SIZES=1
PROD=/srv/ar-local/AR-local
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
REFS=$TMP/refs
PAT='(/srv/ar-local|/var/lib/ar-local|/usr/local/lib/ar-local)[A-Za-z0-9._/@+-]*'

# 1. Text references in host configuration and installed helpers.
grep -rIhoE "$PAT" \
  /etc/systemd /run/systemd/system /etc/ar-local /etc/nginx /etc/sudoers \
  /etc/sudoers.d /etc/ssh /etc/crontab /etc/cron.d /etc/cron.daily \
  /var/spool/cron /etc/tmpfiles.d /etc/logrotate.d /etc/fstab /etc/default \
  /etc/environment /etc/profile.d /home/pi/.bashrc /home/pi/.profile \
  /home/pi/.ssh /root/.ssh /home/pi/.config /usr/local/bin /usr/local/sbin \
  /usr/local/lib/ar-local* /usr/local/lib/shared-pi-queue \
  2>/dev/null | sed 's/^/config\t/' >"$REFS"

# 2. Text references inside durable state and the production checkout.
grep -rIhoE "$PAT" /srv/ar-local/data/state 2>/dev/null \
  | sed 's/^/state\t/' >>"$REFS"
git -C "$PROD" grep -IhoE "$PAT" HEAD -- . ':!docs' ':!tests' 2>/dev/null \
  | sed 's/^/prodcode\t/' >>"$REFS"

# 3. Symlinks pointing into the scan roots.
#    symlink-system: link lives in host config/home. symlink-sibling: link
#    lives inside another /srv/ar-local or /var/lib entry (often other junk).
#    Targets are resolved with realpath -m so relative links count too.
find /etc /usr/local /home /root -maxdepth 6 -xdev \
  -type l -print0 2>/dev/null | xargs -0 -r realpath -m 2>/dev/null | grep -E "^$PAT" \
  | sed 's/^/symlink-system\t/' >>"$REFS"
find /srv/ar-local /var/lib -maxdepth 4 -xdev \
  -type l -print0 2>/dev/null | xargs -0 -r realpath -m 2>/dev/null | grep -E "^$PAT" \
  | sed 's/^/symlink-sibling\t/' >>"$REFS"

# 4. Running processes: cwd, exe, command line, open files.
for p in /proc/[0-9]*; do
  readlink "$p/cwd" "$p/exe" 2>/dev/null
  { tr '\0' '\n' <"$p/cmdline"; } 2>/dev/null
  find "$p/fd" -maxdepth 1 -type l -printf '%l\n' 2>/dev/null
done | grep -oE "$PAT" | sed 's/^/process\t/' >>"$REFS"

# 5. Git worktrees registered in the production repository.
git -C "$PROD" worktree list --porcelain 2>/dev/null \
  | sed -n 's/^worktree //p' | sed 's/^/worktree\t/' >>"$REFS"

sort -u "$REFS" -o "$REFS"

classify() { # $1 = absolute path of a direct child of a scan root
  awk -F'\t' -v e="$1" '
    $2==e || index($2, e "/")==1 { r[$1]=1 }
    END { n=0; for (k in r) { s = s (n++ ? "," : "") k }
          print (n ? "LIVE\t" s : "UNREFERENCED\t-") }' "$REFS"
}

printf 'status\treasons\tmtime\tsize_mb\tpath\n'
{
  find /srv/ar-local -mindepth 1 -maxdepth 1
  find /srv/ar-local/canary -mindepth 1 -maxdepth 1
  find /var/lib /usr/local/lib -mindepth 1 -maxdepth 1 -name 'ar-local*'
} 2>/dev/null | sort | while IFS= read -r e; do
  case "$e" in
    /srv/ar-local/AR-local|/srv/ar-local/data|/srv/ar-local/australianrates|/srv/ar-local/canary|/srv/ar-local/_quarantine)
      st=$'LIVE\tprotected-root' ;;
    *) st=$(classify "$e") ;;
  esac
  sz=-; [ "$SIZES" = 1 ] && sz=$(du -sxBM "$e" 2>/dev/null | cut -f1 | tr -d M)
  printf '%s\t%s\t%s\t%s\n' "$st" "$(date -r "$e" +%F 2>/dev/null)" "$sz" "$e"
done
