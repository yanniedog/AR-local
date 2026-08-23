#!/usr/bin/env sh
set -eu

repo="${1:-/srv/ar-local/AR-local}"
site="${2:-/srv/ar-local/australianrates}"
data="${3:-/srv/ar-local/data}"
config="/etc/ar-local/backup.env"
[ -f "$config" ] || { echo "Missing $config; refusing to install backup timers" >&2; exit 1; }
run_user="$(systemctl show ar-local-daily.service -p User --value)"
run_group="$(systemctl show ar-local-daily.service -p Group --value)"
run_home="$(getent passwd "$run_user" | cut -d: -f6)"
[ -n "$run_user" ] && [ -n "$run_group" ] || { echo "Unable to resolve ingest service identity" >&2; exit 1; }
sudo -u "$run_user" test -r "$config" || {
  echo "$config must be readable by $run_user (recommended root:$run_group 0640)" >&2
  exit 1
}
configured_identity="$(PYTHONPATH="$repo" python3 -c 'from pathlib import Path; from ar_local_backup_policy import BackupPolicy; p=BackupPolicy.from_env_file(Path("/etc/ar-local/backup.env")); print(f"{p.expected_uid}:{p.expected_gid}")')"
service_identity="$(id -u "$run_user"):$(id -g "$run_user")"
[ "$configured_identity" = "$service_identity" ] || {
  echo "Configured backup UID:GID $configured_identity does not match $run_user ($service_identity)" >&2
  exit 1
}
python3 "$repo/pi_backup_foundation.py" preflight --config "$config" --repo "$repo" --site-repo "$site" --data-root "$data"
sudo install -d -o "$run_user" -g "$run_group" -m 0700 /srv/ar-local/restore-drills
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
trusted="/usr/local/lib/ar-local-backup"
sudo install -d -o root -g root -m 0755 "$trusted"
for name in \
  ar_local_backup_policy.py \
  ar_local_boot_proof.py \
  ar_local_checkout.py \
  ar_local_deployment_chain.py \
  ar_local_operation_lock.py \
  pi_backup_foundation.py \
  cdr_atomic.py \
  cdr_export_contract.py \
  cdr_file_lock.py \
  cdr_ledger_v2.py
do
  sudo install -o root -g root -m 0644 "$repo/$name" "$trusted/$name"
done
sudo install -d -o root -g root -m 0755 "$trusted/contracts"
for name in export-contract-v2.schema.json pi-backup-boot-proof-v1.schema.json pi-deployment-acceptance-v1.schema.json pi-preservation-snapshot-v1.schema.json; do
  sudo install -o root -g root -m 0644 "$repo/contracts/$name" "$trusted/contracts/$name"
done
(
  cd "$repo"
  sha256sum \
    ar_local_backup_policy.py \
    ar_local_boot_proof.py \
    ar_local_checkout.py \
    ar_local_deployment_chain.py \
    ar_local_operation_lock.py \
    pi_backup_foundation.py \
    cdr_atomic.py \
    cdr_export_contract.py \
    cdr_file_lock.py \
    cdr_ledger_v2.py \
    contracts/export-contract-v2.schema.json \
    contracts/pi-backup-boot-proof-v1.schema.json \
    contracts/pi-deployment-acceptance-v1.schema.json \
    contracts/pi-preservation-snapshot-v1.schema.json
) > "$tmp/backup-gate.sha256"
sudo install -o root -g root -m 0644 "$tmp/backup-gate.sha256" /etc/ar-local/backup-gate.sha256
for name in ar-local-backup.timer ar-local-restore-drill.timer; do
  sudo install -m 0644 "$repo/deploy/pi/$name" "/etc/systemd/system/$name"
done
sudo install -m 0755 "$repo/deploy/pi/ar-local-restore-latest.sh" /usr/local/bin/ar-local-restore-latest
sudo install -m 0755 "$repo/deploy/pi/ar-local-backup-gate.sh" /usr/local/bin/ar-local-backup-gate
sudo install -m 0755 "$repo/deploy/pi/ar-local-backup-run.sh" /usr/local/bin/ar-local-backup-run
sudo systemctl daemon-reload
sudo systemctl enable --now ar-local-backup.timer ar-local-restore-drill.timer
