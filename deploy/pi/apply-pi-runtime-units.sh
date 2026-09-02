#!/usr/bin/env sh
set -eu

repo_dir="${1:?AR-local repo path is required}"
site_repo="${2:?site repo path is required}"
data_dir="${3:?data root is required}"

repo_dir="$(CDPATH= cd "$repo_dir" && pwd -P)"
site_repo="$(CDPATH= cd "$site_repo" && pwd -P)"
data_dir="$(CDPATH= cd "$data_dir" && pwd -P)"
portable_root="$(dirname "$repo_dir")"
site_root="$site_repo/site"
lock="$data_dir/state/daily-ingest.lock"
tmp_dir=""

acquire_lock() {
  if (set -C; printf 'pid=%s\nrole=deploy-units\n' "$$" > "$lock") 2>/dev/null; then
    return 0
  fi
  owner="$(sed -n 's/^pid=//p' "$lock" 2>/dev/null | head -n 1)"
  case "$owner" in ''|*[!0-9]*) owner="";; esac
  mtime="$(stat -c %Y "$lock" 2>/dev/null || printf 0)"
  now="$(date +%s)"
  if { [ -n "$owner" ] && kill -0 "$owner" 2>/dev/null; } || \
     { [ -z "$owner" ] && [ $((now - mtime)) -le 21600 ]; }; then
    return 75
  fi
  rm -f -- "$lock"
  (set -C; printf 'pid=%s\nrole=deploy-units\n' "$$" > "$lock") 2>/dev/null
}

cleanup() {
  if [ -n "$tmp_dir" ]; then
    case "$tmp_dir" in
      /tmp/*) rm -rf -- "$tmp_dir";;
      *) echo "Refusing unexpected temporary path: $tmp_dir" >&2;;
    esac
  fi
  rm -f -- "$lock"
}

acquire_lock || {
  echo "apply-pi-runtime-units: ingest/deploy lock is busy" >&2
  exit 75
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

run_user="$(systemctl show ar-local-daily.service -p User --value)"
[ -n "$run_user" ] || {
  echo "apply-pi-runtime-units: daily service user is unavailable" >&2
  exit 1
}
run_group="$(systemctl show ar-local-daily.service -p Group --value)"
[ -n "$run_group" ] || run_group="$(id -gn "$run_user")"
run_home="$(getent passwd "$run_user" | cut -d: -f6)"
case "$run_home" in /*) ;; *) echo "Invalid home for $run_user" >&2; exit 1;; esac
[ -d "$site_root" ] || {
  echo "apply-pi-runtime-units: site root is unavailable" >&2
  exit 1
}

escape_sed() {
  printf '%s' "$1" | sed 's/[&|\\]/\\&/g'
}

user_esc="$(escape_sed "$run_user")"
group_esc="$(escape_sed "$run_group")"
home_esc="$(escape_sed "$run_home")"
portable_esc="$(escape_sed "$portable_root")"
repo_esc="$(escape_sed "$repo_dir")"
data_esc="$(escape_sed "$data_dir")"
site_esc="$(escape_sed "$site_root")"

tmp_dir="$(mktemp -d)"
case "$tmp_dir" in /tmp/*) ;; *) echo "Unexpected temporary path" >&2; exit 1;; esac

render_unit() {
  src="$1"
  dst="$2"
  sed \
    -e "s|{{AR_LOCAL_USER}}|$user_esc|g" \
    -e "s|{{AR_LOCAL_GROUP}}|$group_esc|g" \
    -e "s|{{AR_LOCAL_HOME}}|$home_esc|g" \
    -e "s|{{AR_LOCAL_PORTABLE_ROOT}}|$portable_esc|g" \
    -e "s|{{AR_LOCAL_REPO}}|$repo_esc|g" \
    -e "s|{{AR_LOCAL_DATA_ROOT}}|$data_esc|g" \
    -e "s|{{AR_SITE_ROOT}}|$site_esc|g" \
    "$src" > "$dst"
}

for name in \
  ar-local-status.service \
  ar-local-daily.service \
  ar-local-daily-watchdog.service \
  ar-local-ingest-alert.service \
  ar-local-runtime-health.service \
  ar-local-capacity-monitor.service \
  ar-local-boot-recovery.service \
  ar-local-ingest-now.service \
  ar-local-deploy-watchdog.service
do
  render_unit "$repo_dir/deploy/pi/$name" "$tmp_dir/$name"
  sudo install -m 0644 "$tmp_dir/$name" "/etc/systemd/system/$name"
done

for name in \
  ar-local-daily.timer \
  ar-local-daily-watchdog.timer \
  ar-local-deploy-watchdog.timer \
  ar-local-runtime-health.timer \
  ar-local-capacity-monitor.timer
do
  sudo install -m 0644 "$repo_dir/deploy/pi/$name" "/etc/systemd/system/$name"
done
sudo install -m 0755 "$repo_dir/deploy/pi/cdr-ingest" /usr/local/bin/cdr-ingest

sudo systemctl daemon-reload
sudo systemctl enable ar-local-status.service ar-local-boot-recovery.service
sudo systemctl enable --now \
  ar-local-daily.timer \
  ar-local-daily-watchdog.timer \
  ar-local-deploy-watchdog.timer \
  ar-local-runtime-health.timer \
  ar-local-capacity-monitor.timer
sh "$repo_dir/deploy/pi/cutover-status-service.sh"
sudo systemctl restart ar-local-daily.timer ar-local-daily-watchdog.timer
