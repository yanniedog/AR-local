#!/bin/bash
# Source-only installer. Default is a description/check, never an installation.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
if [[ "${1:---check}" == --check && $# -le 1 ]]; then
  cat <<'EOF'
Planned installation: ar-local-ci account with a restricted root-owned login shell,
one exact no-argument sudo helper, no data/source groups and no SSH forwarding.
No activation adapter, deployment approval, key, timer or service will be installed.
Installation requires protected, independently hash-approved read-only staging
and --install ROOT_RECOVERY_APPROVAL_JSON SHA256 ROOT_STAGING_APPROVAL_JSON SHA256.
Proceed only after verified
offsite raw archive, filesystem image, restore/boot proof and off-Pi key custody.
No changes made. Read docs/CI_PI_ACCESS.md before installation and access cutover.
EOF
  exit 0
fi
if [[ $# != 5 || "$1" != --install || ! "$3" =~ ^[0-9a-f]{64}$ || ! "$5" =~ ^[0-9a-f]{64}$ ]]; then
  echo 'Usage: install-ci-access.sh [--check | --install ROOT_RECOVERY_APPROVAL_JSON SHA256 ROOT_STAGING_APPROVAL_JSON SHA256]' >&2
  exit 2
fi
[[ "$EUID" == 0 ]] || { echo 'Explicit installation requires root.' >&2; exit 2; }
approval=$2
approval_sha=$3
# Never import checkout code to decide whether that same code can be trusted.
# The operator independently checks the installer hash BEFORE starting bash.
# This standalone stdlib validator also binds both staged files to that reviewed
# source identity before this installer imports or installs the payload.
/usr/bin/python3 -I - "$0" "$4" "$5" <<'TRUST_PY'
import hashlib, json, os, pathlib, re, stat, sys

def protected_file(path):
    path = pathlib.Path(path)
    if not path.is_absolute() or str(path) != os.path.normpath(path):
        raise ValueError("staging paths must be canonical and absolute")
    for entry in (*reversed(path.parents), path):
        info = entry.lstat()
        leaf = entry == path
        if info.st_uid != 0 or info.st_mode & (0o222 if leaf else 0o022) or stat.S_ISLNK(info.st_mode):
            raise ValueError("staged files must be read-only and exclusively root controlled")
        if leaf:
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024 * 1024:
                raise ValueError("staged file must be a bounded regular file with one link")
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError("staging ancestor is not a directory")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (info.st_uid != 0 or info.st_mode & 0o222 or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1 or info.st_size > 1024 * 1024):
            raise ValueError("staged file changed during validation")
        body = stream.read(1024 * 1024 + 1)
    if len(body) > 1024 * 1024:
        raise ValueError("staged file too large")
    return body

def validate_staging(installer, approval_path, approval_digest):
    installer = pathlib.Path(installer)
    if installer.name != "install-ci-access.sh":
        raise ValueError("unexpected staged installer filename")
    approval_body = protected_file(approval_path)
    if not re.fullmatch(r"[0-9a-f]{64}", approval_digest) or hashlib.sha256(approval_body).hexdigest() != approval_digest:
        raise ValueError("independent staging approval hash differs")
    approval = json.loads(approval_body)
    if (not isinstance(approval, dict) or set(approval) != {"schema_version", "source_commit", "files"}
            or type(approval["schema_version"]) is not int or approval["schema_version"] != 1
            or not isinstance(approval["source_commit"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", approval["source_commit"])
            or not isinstance(approval["files"], dict)
            or set(approval["files"]) != {"install-ci-access.sh", "pi_ci_access.py"}):
        raise ValueError("invalid independently reviewed staging approval")
    for name, digest in approval["files"].items():
        body = protected_file(installer.parent / name)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("staged bytes differ from independent review")

if __name__ == "__main__":
    validate_staging(*sys.argv[1:])
TRUST_PY
staging=${0%/*}
/usr/bin/python3 -I - "$staging/pi_ci_access.py" "$approval" "$approval_sha" <<'PY'
import importlib.util, pathlib, sys
source, approval, digest = sys.argv[1:]
spec = importlib.util.spec_from_file_location("ci_install_validation", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
body = module.trusted_bytes(pathlib.Path(approval))
module.require_digest(body, digest)
module.validate_recovery(body)
for destination in ("/usr/local/sbin", "/usr/local/lib", "/etc/sudoers.d", "/etc/ssh/sshd_config.d", "/var/lib"):
    module.require_root_path(pathlib.Path(destination), directory=True)
for destination in ("/usr/local/sbin/ar-local-ci-login", "/usr/local/sbin/ar-local-ci-control",
                    "/etc/sudoers.d/ar-local-ci", "/etc/ssh/sshd_config.d/80-ar-local-ci.conf",
                    "/etc/ar-local/ci-plans", "/usr/local/lib/ar-local-ci", "/var/lib/ar-local-ci"):
    path = pathlib.Path(destination)
    if path.exists() or path.is_symlink():
        raise SystemExit("Refusing replacement of existing CI access; review/migrate it separately: " + destination)
    ancestor = path.parent
    while not ancestor.exists() and not ancestor.is_symlink():
        ancestor = ancestor.parent
    module.require_root_path(ancestor, directory=True)
PY
if getent passwd ar-local-ci >/dev/null || getent group ar-local-ci >/dev/null; then
  echo 'Existing ar-local-ci account/group requires separate ownership/privilege review; nothing installed.' >&2
  exit 2
fi
for command in /usr/sbin/visudo /usr/sbin/useradd /usr/sbin/sshd /usr/bin/systemd-run /usr/bin/sudo; do
  [[ -x "$command" ]] || { echo "Required command unavailable: $command" >&2; exit 2; }
done
/usr/sbin/sshd -t
umask 077
tmp=$(mktemp -d)
trap 'rm -f -- "$tmp/sudoers" "$tmp/sshd"; rmdir -- "$tmp"' EXIT
cat > "$tmp/sudoers" <<'EOF'
# Exact no-argument entry. The helper validates its bounded JSON input.
Defaults:ar-local-ci env_reset,!setenv
ar-local-ci ALL=(root) NOPASSWD: /usr/local/sbin/ar-local-ci-control ""
EOF
/usr/sbin/visudo -cf "$tmp/sudoers"
cat > "$tmp/sshd" <<'EOF'
Match User ar-local-ci
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    DisableForwarding yes
    PermitTTY no
    PermitUserRC no
    PermitUserEnvironment no
    AuthorizedKeysFile /etc/ssh/ar-local-ci-authorized-keys
Match all
EOF
install -o root -g root -m 0555 "$staging/pi_ci_access.py" /usr/local/sbin/ar-local-ci-login
install -o root -g root -m 0555 "$staging/pi_ci_access.py" /usr/local/sbin/ar-local-ci-control
install -d -o root -g root -m 0755 /usr/local/lib/ar-local-ci /etc/ar-local/ci-plans
install -d -o root -g root -m 0711 /var/lib/ar-local-ci
install -d -o root -g root -m 0755 /var/lib/ar-local-ci/home
/usr/sbin/useradd --system --user-group --home-dir /var/lib/ar-local-ci/home \
  --no-create-home --shell /usr/local/sbin/ar-local-ci-login ar-local-ci
install -d -o pi -g pi -m 0700 /var/lib/ar-local-ci/worker
install -o root -g root -m 0440 "$tmp/sudoers" /etc/sudoers.d/ar-local-ci
install -o root -g root -m 0644 "$tmp/sshd" /etc/ssh/sshd_config.d/80-ar-local-ci.conf
/usr/sbin/visudo -cf /etc/sudoers
/usr/sbin/sshd -t
echo 'Installed restricted account/status boundary. No SSH reload, key, tailnet policy, timer or deployment was activated.'
echo 'Activation remains BLOCKED until a separate reviewed privilege-separated adapter is installed.'
echo 'Retain the owner SSH session; validate policy, effective sshd settings, negative tests and CI cutover before revoking old CI access.'
