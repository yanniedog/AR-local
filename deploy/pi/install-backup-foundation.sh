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
repo=""
site=""
data=""
candidate=""
positional=0

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
      positional=$((positional + 1))
      case "$positional" in
        1) repo=$1 ;;
        2) site=$1 ;;
        3) data=$1 ;;
        4) candidate=$1 ;;
        *)
          echo "Unexpected argument: $1" >&2
          exit 1
          ;;
      esac
      shift
      ;;
  esac
done

repo="${repo:-/srv/ar-local/AR-local}"
site="${site:-/srv/ar-local/australianrates}"
data="${data:-/srv/ar-local/data}"
candidate="${candidate:?approved exact origin/main SHA required}"
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

require_safe_render_value() {
  # Reject control chars and sed metacharacters used by render()'s | delimiter.
  case "$1" in
    *[![:print:]]*|*'|'*|*\\*)
      echo "Unsafe path/value for unit render: contains control or sed metacharacters" >&2
      exit 1
      ;;
  esac
}

sed_escape() {
  # Escape sed replacement metacharacters for delimiter |.
  printf '%s' "$1" | sed -e 's/[&\\|]/\\&/g'
}

require_regular_file() {
  # Refuse symlinks and non-regular files so root install never follows a link
  # from the archived candidate into a host-secret path.
  if [ -L "$1" ] || [ ! -f "$1" ]; then
    echo "Refusing non-regular install source (symlink or missing): $1" >&2
    exit 1
  fi
}

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

tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
source_tree="$tmp/source"
mkdir "$source_tree"
git -C "$repo" archive --format=tar "$candidate" > "$tmp/source.tar"
tar -xf "$tmp/source.tar" -C "$source_tree"
rm -f "$tmp/source.tar"

prod_head_before=""
if [ -n "$prod_repo" ]; then
  prod_head_before="$(git -C "$prod_repo" rev-parse HEAD)"
  echo "PROD_HEAD_BEFORE=$prod_head_before"
  if [ -n "$expect_prod_head" ] && [ "$prod_head_before" != "$expect_prod_head" ]; then
    echo "Production HEAD $prod_head_before does not match --expect-prod-head $expect_prod_head" >&2
    exit 1
  fi
fi

run_user=""
run_group=""
run_home=""
if [ "$gate_bytes_only" -eq 0 ]; then
  run_user="$(systemctl show ar-local-daily.service -p User --value)"
  run_group="$(systemctl show ar-local-daily.service -p Group --value)"
  if [ -z "$run_group" ] && [ -n "$run_user" ]; then
    run_group="$(id -gn "$run_user")"
  fi
  run_home="$(getent passwd "$run_user" | cut -d: -f6)"
  [ -n "$run_user" ] && [ -n "$run_group" ] || { echo "Unable to resolve ingest service identity" >&2; exit 1; }

  [ -f "$config" ] || { echo "Missing $config; refusing to install backup timers" >&2; exit 1; }
  sudo -u "$run_user" test -r "$config" || {
    echo "$config must be readable by $run_user (recommended root:$run_group 0640)" >&2
    exit 1
  }
  configured_identity="$(PYTHONPATH="$source_tree" python3 -c 'from pathlib import Path; from ar_local_backup_policy import BackupPolicy; p=BackupPolicy.from_env_file(Path("/etc/ar-local/backup.env")); print(f"{p.expected_uid}:{p.expected_gid}")')"
  service_identity="$(id -u "$run_user"):$(id -g "$run_user")"
  [ "$configured_identity" = "$service_identity" ] || {
    echo "Configured backup UID:GID $configured_identity does not match $run_user ($service_identity)" >&2
    exit 1
  }
  python3 "$source_tree/pi_backup_foundation.py" preflight --config "$config" --repo "$repo" --site-repo "$site" --data-root "$data"

  require_safe_render_value "$run_user"
  require_safe_render_value "$run_group"
  require_safe_render_value "$run_home"
  require_safe_render_value "$repo"
  require_safe_render_value "$data"
  require_safe_render_value "$site/site"

  sudo install -d -o "$run_user" -g "$run_group" -m 0700 /srv/ar-local/restore-drills
  render() {
    sed -e "s|{{AR_LOCAL_USER}}|$(sed_escape "$run_user")|g" \
      -e "s|{{AR_LOCAL_GROUP}}|$(sed_escape "$run_group")|g" \
      -e "s|{{AR_LOCAL_HOME}}|$(sed_escape "$run_home")|g" \
      -e "s|{{AR_LOCAL_REPO}}|$(sed_escape "$repo")|g" \
      -e "s|{{AR_LOCAL_DATA_ROOT}}|$(sed_escape "$data")|g" \
      -e "s|{{AR_SITE_ROOT}}|$(sed_escape "$site/site")|g" "$1" > "$2"
  }
  for name in ar-local-backup.service ar-local-restore-drill.service; do
    require_regular_file "$source_tree/deploy/pi/$name"
    render "$source_tree/deploy/pi/$name" "$tmp/$name"
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
  require_regular_file "$source_tree/$name"
  sudo install -o root -g root -m 0644 "$source_tree/$name" "$trusted/$name"
done
sudo install -d -o root -g root -m 0755 "$trusted/contracts"
for name in export-contract-v2.schema.json observation-v1.schema.json product-accounting-v1.schema.json pi-backup-boot-proof-v1.schema.json pi-deployment-acceptance-v1.schema.json pi-preservation-snapshot-v1.schema.json pi-restore-acceptance-v1.schema.json pi-rollback-acceptance-v1.schema.json; do
  require_regular_file "$source_tree/contracts/$name"
  sudo install -o root -g root -m 0644 "$source_tree/contracts/$name" "$trusted/contracts/$name"
done
(
  cd "$source_tree"
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

if [ "$gate_bytes_only" -eq 0 ]; then
  for name in ar-local-backup.timer ar-local-restore-drill.timer; do
    require_regular_file "$source_tree/deploy/pi/$name"
    sudo install -m 0644 "$source_tree/deploy/pi/$name" "/etc/systemd/system/$name"
  done
fi

for wrapper_src in \
  deploy/pi/ar-local-restore-latest.sh \
  deploy/pi/ar-local-backup-gate.sh \
  deploy/pi/ar-local-backup-run.sh
do
  require_regular_file "$source_tree/$wrapper_src"
done
sudo install -m 0755 "$source_tree/deploy/pi/ar-local-restore-latest.sh" /usr/local/bin/ar-local-restore-latest
sudo install -m 0755 "$source_tree/deploy/pi/ar-local-backup-gate.sh" /usr/local/bin/ar-local-backup-gate
sudo install -m 0755 "$source_tree/deploy/pi/ar-local-backup-run.sh" /usr/local/bin/ar-local-backup-run

# Record wrappers under their installed absolute paths so both this installer and
# runtime `ar-local-backup-gate` (cd $trusted && sha256sum -c) accept the same
# manifest. Relative deploy/pi/ paths are not present on the installed layout.
append_installed_wrapper_hash() {
  src="$1"
  dest="$2"
  hash="$(sha256sum < "$source_tree/$src" | awk '{print $1}')"
  printf '%s  %s\n' "$hash" "$dest" >> "$tmp/backup-gate.sha256"
}
append_installed_wrapper_hash deploy/pi/ar-local-restore-latest.sh /usr/local/bin/ar-local-restore-latest
append_installed_wrapper_hash deploy/pi/ar-local-backup-gate.sh /usr/local/bin/ar-local-backup-gate
append_installed_wrapper_hash deploy/pi/ar-local-backup-run.sh /usr/local/bin/ar-local-backup-run

sudo install -d -o root -g root -m 0755 /etc/ar-local
sudo install -o root -g root -m 0644 "$tmp/backup-gate.sha256" /etc/ar-local/backup-gate.sha256

# Relative lib/schema paths resolve under $trusted; absolute wrapper paths verify
# from any cwd. This matches runtime ar-local-backup-gate verification.
if ! (cd "$trusted" && sha256sum --quiet -c /etc/ar-local/backup-gate.sha256); then
  echo "Installed backup-gate bytes failed sha256sum verification against /etc/ar-local/backup-gate.sha256" >&2
  exit 1
fi

test -x /usr/local/bin/ar-local-backup-gate
test -x /usr/local/bin/ar-local-backup-run
test -x /usr/local/bin/ar-local-restore-latest

disable_backup_timers() {
  sudo systemctl disable --now ar-local-backup.timer ar-local-restore-drill.timer >/dev/null 2>&1 || true
}

# Re-check production pin before enabling timers so a moved HEAD fail-closes
# without leaving timers live. A later after-check disables timers on drift.
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
  if ! sudo systemctl enable --now ar-local-backup.timer ar-local-restore-drill.timer; then
    echo "Timer enable/start failed; disabling both backup timers" >&2
    disable_backup_timers
    exit 1
  fi
  if [ -n "$prod_repo" ]; then
    prod_head_after_enable="$(git -C "$prod_repo" rev-parse HEAD)"
    echo "PROD_HEAD_AFTER_ENABLE=$prod_head_after_enable"
    if [ "$prod_head_after_enable" != "$prod_head_before" ]; then
      echo "Production HEAD drifted during/after timer enable — disabling timers" >&2
      disable_backup_timers
      exit 1
    fi
  fi
else
  echo "GATE_BYTES_ONLY_OK"
  echo "SKIPPED=backup.env,mount-preflight,systemd-units,timers,restore-drills-dir"
fi

if [ -n "$prod_repo" ]; then
  prod_head_after="$(git -C "$prod_repo" rev-parse HEAD)"
  echo "PROD_HEAD_AFTER=$prod_head_after"
  if [ "$prod_head_after" != "$prod_head_before" ]; then
    echo "Production HEAD drifted after install steps — FAIL" >&2
    if [ "$gate_bytes_only" -eq 0 ]; then
      disable_backup_timers
    fi
    exit 1
  fi
fi
