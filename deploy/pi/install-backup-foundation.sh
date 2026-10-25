#!/usr/bin/env sh
# Install trusted backup-gate bytes (and optionally full foundation timers).
#
# Full install (default): requires /etc/ar-local/backup.env, preflight, and
# HEAD==origin/main==candidate on the supplied repo path, then enables timers.
#
# Gate-bytes-only (--gate-bytes-only): installs /usr/local gate lib+bins+manifest
# from an aligned source tree without requiring backup.env, mount preflight, or
# timer enable. Use a disposable checkout at the approved origin/main SHA so
# production /srv/ar-local/AR-local can remain on a prior protected pin.
set -eu

gate_bytes_only=0
prod_repo=""
expect_prod_head=""
while [ $# -gt 0 ]; do
  case "$1" in
    --gate-bytes-only)
      gate_bytes_only=1
      shift
      ;;
    --prod-repo)
      prod_repo="${2:?--prod-repo requires a path}"
      shift 2
      ;;
    --expect-prod-head)
      expect_prod_head="${2:?--expect-prod-head requires a 40-char SHA}"
      shift 2
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

repo="${1:-/srv/ar-local/AR-local}"
site="${2:-/srv/ar-local/australianrates}"
data="${3:-/srv/ar-local/data}"
candidate="${4:?approved exact origin/main SHA required}"
config="/etc/ar-local/backup.env"

case "$candidate" in *[!0-9a-f]*|'') echo "Invalid approved candidate SHA" >&2; exit 1;; esac
[ "${#candidate}" -eq 40 ] || { echo "Approved candidate SHA must be 40 characters" >&2; exit 1; }
if [ -n "$expect_prod_head" ] && [ -z "$prod_repo" ]; then
  echo "--expect-prod-head requires --prod-repo" >&2
  exit 1
fi
if [ -n "$expect_prod_head" ]; then
  case "$expect_prod_head" in *[!0-9a-f]*|'') echo "Invalid --expect-prod-head SHA" >&2; exit 1;; esac
  [ "${#expect_prod_head}" -eq 40 ] || { echo "--expect-prod-head must be 40 characters" >&2; exit 1; }
fi

[ -z "$(git -C "$repo" status --porcelain --untracked-files=all)" ] || {
  echo "AR-local source checkout is dirty; refusing to install trusted gate bytes" >&2
  exit 1
}
[ "$(git -C "$repo" rev-parse HEAD)" = "$candidate" ] && \
  [ "$(git -C "$repo" rev-parse origin/main)" = "$candidate" ] || {
  echo "Source checkout is not the approved exact origin/main commit" >&2
  echo "Hint: pass a disposable aligned tree as repo= (not production) with --gate-bytes-only" >&2
  exit 1
}

prod_head_before=""
if [ -n "$prod_repo" ]; then
  prod_head_before="$(git -C "$prod_repo" rev-parse HEAD)"
  echo "PROD_HEAD_BEFORE=$prod_head_before"
  if [ -n "$expect_prod_head" ] && [ "$prod_head_before" != "$expect_prod_head" ]; then
    echo "Production HEAD $prod_head_before does not match --expect-prod-head $expect_prod_head" >&2
    exit 1
  fi
fi

run_user="$(systemctl show ar-local-daily.service -p User --value)"
run_group="$(systemctl show ar-local-daily.service -p Group --value)"
run_home="$(getent passwd "$run_user" | cut -d: -f6)"
[ -n "$run_user" ] && [ -n "$run_group" ] || { echo "Unable to resolve ingest service identity" >&2; exit 1; }

if [ "$gate_bytes_only" -eq 0 ]; then
  [ -f "$config" ] || { echo "Missing $config; refusing to install backup timers" >&2; exit 1; }
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
fi

tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT

if [ "$gate_bytes_only" -eq 0 ]; then
  sudo install -d -o "$run_user" -g "$run_group" -m 0700 /srv/ar-local/restore-drills
  render() {
    sed -e "s|{{AR_LOCAL_USER}}|$run_user|g" -e "s|{{AR_LOCAL_GROUP}}|$run_group|g" \
      -e "s|{{AR_LOCAL_HOME}}|$run_home|g" -e "s|{{AR_LOCAL_REPO}}|$repo|g" \
      -e "s|{{AR_LOCAL_DATA_ROOT}}|$data|g" -e "s|{{AR_SITE_ROOT}}|$site/site|g" "$1" > "$2"
  }
  for name in ar-local-backup.service ar-local-restore-drill.service; do
    render "$repo/deploy/pi/$name" "$tmp/$name"
    sudo install -m 0644 "$tmp/$name" "/etc/systemd/system/$name"
  done
fi

trusted="/usr/local/lib/ar-local-backup"
sudo install -d -o root -g root -m 0755 "$trusted"
for name in \
  ar_local_backup_policy.py \
  ar_local_backup_scope.py \
  ar_local_boot_proof.py \
  ar_local_checkout.py \
  ar_local_deployment_chain.py \
  ar_local_operation_lock.py \
  ar_local_rollback_record.py \
  ar_local_restore_verification.py \
  ar_local_restore_io.py \
  ar_local_ingest_schedule.py \
  pi_backup_foundation.py \
  pi_ingest_terminal.py \
  process_safety.py \
  cdr_atomic.py \
  cdr_export_contract.py \
  cdr_file_lock.py \
  cdr_ledger_v2.py \
  cdr_attempt_evidence_promotion.py \
  cdr_compatibility.py \
  cdr_contracts.py \
  cdr_http_policy.py \
  cdr_ingest_support.py \
  cdr_journal_evidence.py \
  cdr_observation.py \
  cdr_observation_db.py \
  cdr_observation_db_build.py \
  cdr_observation_db_schema.py \
  cdr_partial_index.py \
  cdr_product_accounting.py \
  cdr_product_classification.py \
  cdr_provider_identity_registry.py \
  cdr_public_projection.py \
  cdr_quality_sqlite.py \
  cdr_sqlite_budget.py \
  cdr_raw_attempt_journal.py \
  cdr_upstream_dependency.py \
  laptop_backup_daily_verify.py
do
  sudo install -o root -g root -m 0644 "$repo/$name" "$trusted/$name"
done
sudo install -d -o root -g root -m 0755 "$trusted/contracts"
for name in export-contract-v2.schema.json observation-v1.schema.json product-accounting-v1.schema.json pi-backup-boot-proof-v1.schema.json pi-deployment-acceptance-v1.schema.json pi-preservation-snapshot-v1.schema.json pi-restore-acceptance-v1.schema.json pi-rollback-acceptance-v1.schema.json; do
  sudo install -o root -g root -m 0644 "$repo/contracts/$name" "$trusted/contracts/$name"
done
(
  cd "$repo"
  sha256sum \
    ar_local_backup_policy.py \
    ar_local_backup_scope.py \
    ar_local_boot_proof.py \
    ar_local_checkout.py \
    ar_local_deployment_chain.py \
    ar_local_operation_lock.py \
    ar_local_rollback_record.py \
    ar_local_restore_verification.py \
    ar_local_restore_io.py \
    ar_local_ingest_schedule.py \
    pi_backup_foundation.py \
    pi_ingest_terminal.py \
    process_safety.py \
    cdr_atomic.py \
    cdr_export_contract.py \
    cdr_file_lock.py \
    cdr_ledger_v2.py \
    cdr_attempt_evidence_promotion.py \
    cdr_compatibility.py \
    cdr_contracts.py \
    cdr_http_policy.py \
    cdr_ingest_support.py \
    cdr_journal_evidence.py \
    cdr_observation.py \
    cdr_observation_db.py \
    cdr_observation_db_build.py \
    cdr_observation_db_schema.py \
    cdr_partial_index.py \
    cdr_product_accounting.py \
    cdr_product_classification.py \
    cdr_provider_identity_registry.py \
    cdr_public_projection.py \
    cdr_quality_sqlite.py \
    cdr_sqlite_budget.py \
    cdr_raw_attempt_journal.py \
    cdr_upstream_dependency.py \
    laptop_backup_daily_verify.py \
    contracts/export-contract-v2.schema.json \
    contracts/observation-v1.schema.json \
    contracts/product-accounting-v1.schema.json \
    contracts/pi-backup-boot-proof-v1.schema.json \
    contracts/pi-deployment-acceptance-v1.schema.json \
    contracts/pi-preservation-snapshot-v1.schema.json \
    contracts/pi-restore-acceptance-v1.schema.json \
    contracts/pi-rollback-acceptance-v1.schema.json
) > "$tmp/backup-gate.sha256"
sudo install -d -o root -g root -m 0755 /etc/ar-local
sudo install -o root -g root -m 0644 "$tmp/backup-gate.sha256" /etc/ar-local/backup-gate.sha256

if [ "$gate_bytes_only" -eq 0 ]; then
  for name in ar-local-backup.timer ar-local-restore-drill.timer; do
    sudo install -m 0644 "$repo/deploy/pi/$name" "/etc/systemd/system/$name"
  done
fi

sudo install -m 0755 "$repo/deploy/pi/ar-local-restore-latest.sh" /usr/local/bin/ar-local-restore-latest
sudo install -m 0755 "$repo/deploy/pi/ar-local-backup-gate.sh" /usr/local/bin/ar-local-backup-gate
sudo install -m 0755 "$repo/deploy/pi/ar-local-backup-run.sh" /usr/local/bin/ar-local-backup-run

if ! (cd "$trusted" && sha256sum --quiet -c /etc/ar-local/backup-gate.sha256); then
  echo "Installed backup-gate bytes failed sha256sum verification against /etc/ar-local/backup-gate.sha256" >&2
  exit 1
fi
test -x /usr/local/bin/ar-local-backup-gate
test -x /usr/local/bin/ar-local-backup-run
test -x /usr/local/bin/ar-local-restore-latest

# Re-check production pin before enabling timers so a moved HEAD fail-closes
# without leaving timers live. A later after-check only detects post-enable drift.
if [ -n "$prod_repo" ]; then
  prod_head_mid="$(git -C "$prod_repo" rev-parse HEAD)"
  echo "PROD_HEAD_BEFORE_ENABLE=$prod_head_mid"
  [ "$prod_head_mid" = "$prod_head_before" ] || {
    echo "Production HEAD changed during install before timer enable — FAIL" >&2
    exit 1
  }
fi

if [ "$gate_bytes_only" -eq 0 ]; then
  sudo systemctl daemon-reload
  sudo systemctl enable --now ar-local-backup.timer ar-local-restore-drill.timer
else
  echo "GATE_BYTES_ONLY_OK"
  echo "SKIPPED=backup.env,mount-preflight,systemd-units,timers,restore-drills-dir"
fi

if [ -n "$prod_repo" ]; then
  prod_head_after="$(git -C "$prod_repo" rev-parse HEAD)"
  echo "PROD_HEAD_AFTER=$prod_head_after"
  [ "$prod_head_after" = "$prod_head_before" ] || {
    echo "Production HEAD drifted after install steps — FAIL (timers may already be live in full-install mode)" >&2
    exit 1
  }
fi
