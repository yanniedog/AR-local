#!/usr/bin/env sh
set -eu

repo="${1:-/srv/ar-local/AR-local}"
site="${2:-/srv/ar-local/australianrates}"
data="${3:-/srv/ar-local/data}"
config="/etc/ar-local/backup.env"
[ -f "$config" ] || { echo "Missing $config; refusing to install backup timers" >&2; exit 1; }
python3 "$repo/pi_backup_foundation.py" preflight --config "$config" --repo "$repo" --site-repo "$site" --data-root "$data"
run_user="$(systemctl show ar-local-daily.service -p User --value)"
run_group="$(systemctl show ar-local-daily.service -p Group --value)"
run_home="$(getent passwd "$run_user" | cut -d: -f6)"
[ -n "$run_user" ] && [ -n "$run_group" ] || { echo "Unable to resolve ingest service identity" >&2; exit 1; }
sudo -u "$run_user" test -r "$config" || {
  echo "$config must be readable by $run_user (recommended root:$run_group 0640)" >&2
  exit 1
}
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
render() {
  sed -e "s|{{AR_LOCAL_USER}}|$run_user|g" -e "s|{{AR_LOCAL_GROUP}}|$run_group|g" \
    -e "s|{{AR_LOCAL_HOME}}|$run_home|g" -e "s|{{AR_LOCAL_REPO}}|$repo|g" \
    -e "s|{{AR_LOCAL_DATA_ROOT}}|$data|g" -e "s|{{AR_SITE_ROOT}}|$site/site|g" "$1" > "$2"
}
for name in ar-local-backup.service ar-local-restore-drill.service; do
  render "$repo/deploy/pi/$name" "$tmp/$name"
  sudo install -m 0644 "$tmp/$name" "/etc/systemd/system/$name"
done
for name in ar-local-backup.timer ar-local-restore-drill.timer; do
  sudo install -m 0644 "$repo/deploy/pi/$name" "/etc/systemd/system/$name"
done
sudo install -m 0755 "$repo/deploy/pi/ar-local-restore-latest.sh" /usr/local/bin/ar-local-restore-latest
sudo systemctl daemon-reload
sudo systemctl enable --now ar-local-backup.timer ar-local-restore-drill.timer
