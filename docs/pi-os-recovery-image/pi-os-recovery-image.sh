#!/bin/bash
# Monthly Pi OS recovery set -> Google Drive (file-level, zstd -19 --long=27).
# Rebuilds this Pi on new hardware together with the daily CDR archives that
# are already on Drive. Same layout as the manual 2026-10-28 set.
# Installed as /usr/local/sbin/pi-os-recovery-image; run by pi-os-recovery-image.timer.
# Never deletes anything on Drive. Drive/restic credentials are excluded.
set -euo pipefail
umask 077
export LC_ALL=C TZ=Australia/Hobart

ENVFILE=/etc/ar-local/day-archive.env
DISK=/dev/nvme0n1
BOOT_PART=${DISK}p1
STAMP=$(date +%Y-%m-%d)
WORK=/var/lib/pi-os-recovery-image
SET=$WORK/$STAMP
LEVEL=19
THREADS=3

log() { echo "$(date -Is) $*" | tee -a "$WORK/run.log"; }
fail() { log "FAILED: $*"; echo "{\"date\":\"$STAMP\",\"result\":\"FAILED\",\"reason\":\"$*\",\"at\":\"$(date -Is)\"}" > "$WORK/last-result.json"; chmod 644 "$WORK/last-result.json"; exit 1; }

[ "$(id -u)" = 0 ] || { echo "must run as root" >&2; exit 2; }
mkdir -p "$WORK"; chmod 755 "$WORK"

# Stay clear of the protected ingest window (00:30-03:30) and of live ingest.
now=$((10#$(date +%H) * 60 + 10#$(date +%M)))
{ [ "$now" -ge 215 ] && [ "$now" -le 1200 ]; } || fail "outside 03:35-20:00 Hobart start window"
for unit in ar-local-daily.service ar-local-ingest-now.service; do
  systemctl is-active -q "$unit" && fail "$unit is active"
done

set -a; . "$ENVFILE"; set +a
[ -n "${AR_LOCAL_DAY_ARCHIVE_REMOTE:-}" ] && [ -n "${RCLONE_CONFIG:-}" ] || fail "Drive remote not configured"
# rclone rewrites its config when it refreshes the token. As root that turned the
# shared credential root-owned and broke the hourly day-archive drain (user pi) on
# 2026-11-15. Work from a private copy; the shared file is never opened for writing.
SHARED_RCLONE_CONFIG=$RCLONE_CONFIG
shared_owner=$(stat -c %u:%g:%a "$SHARED_RCLONE_CONFIG")
install -m 600 "$SHARED_RCLONE_CONFIG" "$WORK/.rclone-private.conf"
export RCLONE_CONFIG="$WORK/.rclone-private.conf"
trap 'rm -f "$WORK/.rclone-private.conf"; [ "$(stat -c %u:%g:%a "$SHARED_RCLONE_CONFIG")" = "$shared_owner" ] || echo "$(date -Is) WARNING shared rclone config ownership changed" >> "$WORK/run.log"' EXIT
REMOTE="${AR_LOCAL_DAY_ARCHIVE_REMOTE%/*}/monthly-os-recovery/$STAMP-$(hostname)"
if [ -n "$(rclone lsf "$REMOTE/_meta/COMPLETE.json" 2>/dev/null)" ]; then log "set $STAMP already complete on Drive"; exit 0; fi

avail=$(df --output=avail -B1 "$WORK" | tail -1)
[ "$avail" -gt $((40 * 1024 * 1024 * 1024)) ] || fail "less than 40 GiB free for staging"
rm -rf "$SET"; mkdir -p "$SET/os" "$SET/arlocal" "$SET/_meta"
log "BEGIN set=$STAMP remote=$REMOTE"

# ---- metadata needed to rebuild on a blank disk
M=$SET/_meta
sfdisk -d "$DISK" > "$SET/os/$(basename "$DISK").sfdisk"
blkid > "$M/blkid.txt"; lsblk -J -o NAME,SIZE,TYPE,FSTYPE,LABEL,UUID,PARTUUID,MOUNTPOINT > "$M/lsblk.json"
findmnt -A > "$M/findmnt.txt"; df -h > "$M/df.txt"; cp /etc/fstab "$M/fstab"
cp /boot/firmware/cmdline.txt /boot/firmware/config.txt "$M/"
tr -d '\0' < /proc/device-tree/model > "$M/model.txt" || true
rpi-eeprom-config > "$M/rpi-eeprom-config.txt" 2>/dev/null || true
dpkg --get-selections > "$M/dpkg-selections.txt"
pip3 freeze > "$M/pip3-freeze.txt" 2>/dev/null || true
systemctl list-unit-files --no-pager > "$M/systemd-unit-files.txt"
systemctl list-timers --all --no-pager > "$M/systemd-timers.txt"
{ uname -a; cat /etc/os-release; } > "$M/system.txt"
for repo in /srv/ar-local/AR-local /srv/ar-local/australianrates; do
  [ -d "$repo/.git" ] && echo "$repo $(git -C "$repo" rev-parse HEAD 2>/dev/null)" >> "$M/git-heads.txt"
done

pack() {  # pack <name> <output> <tar args...>
  local name=$1 out=$2; shift 2
  local start=$SECONDS rc=0
  log "BEGIN $name"
  set +e
  tar --create --file=- --xattrs --acls --numeric-owner --sort=name "$@" 2> "$M/$name.tar.stderr" \
    | zstd -q -$LEVEL --long=27 -T$THREADS -o "$out"
  local st=("${PIPESTATUS[@]}")
  set -e
  rc=${st[0]}; local zrc=${st[1]}
  # tar exit 1 = a file changed while being read (expected on a live system).
  { [ "$rc" -le 1 ] && [ "$zrc" = 0 ]; } || fail "$name tar_rc=$rc zstd_rc=$zrc"
  zstd -t -q --long=27 "$out" || fail "$name archive failed its integrity test"
  log "built $name bytes=$(stat -c %s "$out") tar_rc=$rc secs=$((SECONDS - start))"
}

# ---- boot: raw partition image, file copy, and the first 4 MiB of the disk
dd if="$BOOT_PART" bs=4M status=none | zstd -q -$LEVEL -T$THREADS -o "$SET/os/$(basename "$BOOT_PART")-boot-firmware.img.zst"
dd if="$DISK" bs=1M count=4 status=none | zstd -q -$LEVEL -o "$SET/os/$(basename "$DISK")-first-4MiB.bin.zst"
pack os-boot-tar "$SET/os/boot-firmware.tar.zst" -C /boot/firmware .

# ---- root filesystem (this filesystem only; bulky AR-local trees handled below)
excludes=(--exclude=./srv/ar-local --exclude=./var/lib/ar-local-drive-backup
  --exclude=./var/lib/ar-local-plain-backup-work --exclude='./var/lib/ar-local-os-backup-*'
  --exclude=./var/lib/pi-os-recovery-image --exclude=./var/cache --exclude='./var/tmp/*'
  --exclude='./tmp/*' --exclude='./home/*/.cache' --exclude=./var/log/journal
  --exclude=./var/swap --exclude=./swapfile --exclude=./lost+found)
for secret in "$SHARED_RCLONE_CONFIG" "${RESTIC_PASSWORD_FILE:-}"; do
  [ -n "$secret" ] && excludes+=("--exclude=.$secret")
done
restic_secret=$(sed -n 's/^RESTIC_PASSWORD_FILE=//p' /etc/ar-local/drive-backup.env 2>/dev/null | tr -d '"' | head -1)
[ -n "$restic_secret" ] && excludes+=("--exclude=.$restic_secret")
pack os-rootfs "$SET/os/rootfs-$(basename "$DISK")p2.tar.zst" --one-file-system "${excludes[@]}" -C / .

# ---- AR-local: code, runtime state, last seven finalized days
code=(AR-local australianrates)
for dir in /srv/ar-local/quality-python-*; do [ -d "$dir" ] && code+=("$(basename "$dir")"); done
pack ar-code "$SET/arlocal/srv-ar-local-code.tar.zst" -C /srv/ar-local "${code[@]}"
pack ar-state "$SET/arlocal/srv-ar-local-data-state.tar.zst" -C /srv/ar-local/data state
mapfile -t runs < <(cd /srv/ar-local/data/runs && ls -d 20??-??-?? 2>/dev/null | sort | tail -7)
if [ "${#runs[@]}" -gt 0 ]; then
  printf '%s\n' "${runs[@]}" > "$M/runs-included.txt"
  pack ar-runs-last7 "$SET/arlocal/srv-ar-local-data-runs-last7.tar.zst" -C /srv/ar-local/data/runs "${runs[@]}"
fi

cat > "$M/RESTORE.md" <<'RESTORE'
# Restore (Raspberry Pi 5, NVMe) - file-level rootfs + boot
1. Boot the new Pi from any Raspberry Pi OS medium with the target NVMe attached.
2. Partition the target from os/nvme0n1.sfdisk (p1 vfat 512 MiB, p2 ext4 rest; the
   label-id line restores the original PARTUUIDs): sfdisk /dev/nvme0n1 < nvme0n1.sfdisk
   If the new disk is smaller, edit the size of partition 2 first. mkfs.vfat -n BOOTFS p1; mkfs.ext4 -L rootfs p2.
3. Boot: zstd -dc os/boot-firmware.tar.zst | tar -x -C /mnt/boot
   (or write os/nvme0n1p1-boot-firmware.img.zst to p1 with dd).
4. Root: zstd -dc --long=27 os/rootfs-nvme0n1p2.tar.zst | tar -x --xattrs --acls --numeric-owner -C /mnt/root
   then mkdir -p /mnt/root/{proc,sys,dev,run,tmp,mnt,media,var/tmp,var/cache,srv/ar-local/data}.
5. Check PARTUUID in /mnt/root/etc/fstab and /mnt/boot/cmdline.txt against blkid of the new disk.
6. AR-local: arlocal/srv-ar-local-code -> /srv/ar-local ; srv-ar-local-data-state -> /srv/ar-local/data ;
   srv-ar-local-data-runs-last7 -> /srv/ar-local/data/runs. All with zstd -dc --long=27 | tar -x --numeric-owner.
7. Full CDR history is NOT in this set: restore it from Drive daily-cdr-raw-records / daily-cdr-day-archives.
8. Not on Drive by design: the rclone Drive credential and restic password. Re-enrol rclone after rebuild.
9. Verify every file first with: sha256sum -c _meta/SHA256SUMS
RESTORE

( cd "$SET" && find os arlocal -type f -print0 | sort -z | xargs -0 sha256sum > _meta/SHA256SUMS )
( cd "$SET" && find os arlocal -type f -printf '%p\t%s\n' | sort > _meta/manifest.tsv )

log "uploading"
rclone copy "$SET" "$REMOTE" --immutable --transfers 2 --drive-chunk-size 64M --log-file "$WORK/rclone-$STAMP.log" --log-level NOTICE \
  || fail "upload failed"
rclone check "$SET" "$REMOTE" --one-way --log-file "$WORK/rclone-check-$STAMP.log" --log-level NOTICE \
  || fail "Drive copy does not match local set"

total=$(du -sb "$SET" | cut -f1)
cat > "$M/COMPLETE.json" <<JSON
{"date":"$STAMP","host":"$(hostname)","remote":"$REMOTE","compressed_bytes":$total,
 "sha256sums_sha256":"$(sha256sum "$M/SHA256SUMS" | cut -d' ' -f1)","completed_at":"$(date -Is)",
 "verified":"rclone check one-way size+hash","credentials_on_drive":false}
JSON
rclone copyto "$M/COMPLETE.json" "$REMOTE/_meta/COMPLETE.json" || fail "completion marker upload failed"

# Keep only the small metadata locally; the archives now live on Drive.
rm -rf "$SET/os" "$SET/arlocal"
find "$WORK" -mindepth 1 -maxdepth 1 -type d -name '20??-??-??' ! -name "$STAMP" -mtime +200 -exec rm -rf {} +
cp "$M/COMPLETE.json" "$WORK/last-result.json"; chmod 644 "$WORK/last-result.json"
log "DONE bytes=$total remote=$REMOTE"
