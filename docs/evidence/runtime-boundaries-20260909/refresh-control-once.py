"""One-time user-authorized September 9 early backup; no installed files changed."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RECEIVER = Path(r"C:\code\backups\AR-local-user-session\source-auth-publication-20260908-v4\source")
CONFIG = RECEIVER.parent / "user-session-backup.json"
CONFIG_SHA = "5bdb944363ec5276ea8662f99ba4d37e3852f2049bb8fd590a8cc2f664b798ca"
SOURCE_SHA = "96c7770805b67ecdc7dd1930e7bf0ec2a9959598ec8d7296b3ce496519f766e8"
source = RECEIVER / "laptop_backup_user_session.py"
if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA:
    raise RuntimeError("Installed runner source changed")
sys.path.insert(0, str(RECEIVER))
import laptop_backup_user_session as runner

config = runner.load_config(CONFIG, CONFIG_SHA)
runner.verify_release(config)
now = datetime.now(timezone.utc).astimezone(runner.HOBART)
if now.date().isoformat() != "2026-09-09" or not runner.allowed_start(datetime.now(timezone.utc)):
    raise RuntimeError("Check-only authorization has expired")
attempt = Path(__file__).with_name("control-refresh-authority.json")
with attempt.open("x", encoding="utf-8") as stream:
    json.dump({"user_instruction": "Do it now rather than 6am.",
               "at": now.isoformat(), "config_sha256": CONFIG_SHA,
               "installed_source_sha256": SOURCE_SHA,
               "wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "scope": "Control-only refresh September 9 after original preflight verifies other components; full original post-verification; one-connection cleanup; SSH ConnectTimeout=60 seconds; ordinary token, identity, locks, quiet-window and receiver preflight retained",
               "natural_trigger": False}, stream, indent=2)

def authorized_start(instant):
    local = instant.astimezone(runner.HOBART)
    return local.date().isoformat() == "2026-09-09" and local.hour == 5

# Only this process's scheduling predicate changes. execute retains all remaining
# installed checks and holds the same whole-job lock; scheduled.main also keeps
# its separate quiet-window, production identity and source validation checks.
# Installed start-time predicate is retained for this check-only pass.
# A bounded connection timeout increase addresses observed 10-second SSH banner
# timeouts. All authentication, endpoint, host-key and executable checks remain.
if hashlib.sha256((RECEIVER / "laptop_backup_transport.py").read_bytes()).hexdigest() != "85901b815ff94ac3f335fad7f2968ddd296ace30ba9bec54cad816dad01dc997":
    raise RuntimeError("Installed transport source changed")
import laptop_backup_transport as transport
original_ssh_options = transport.ssh_options
def tolerant_ssh_options(*args, **kwargs):
    options = original_ssh_options(*args, **kwargs)
    if options.count("ConnectTimeout=10") != 1:
        raise RuntimeError("Unexpected SSH timeout contract")
    return ["ConnectTimeout=60" if item == "ConnectTimeout=10" else item for item in options]
transport.ssh_options = tolerant_ssh_options

# The observed LAN is slow (566-1533ms ICMP). Extend only already-bounded
# SSH/SCP helper calls from30 to90 seconds; unrelated command limits stay intact.
original_run = transport.subprocess.run
pinned_network_executables = {config["transport"]["ssh_path"], config["transport"]["scp_path"]}
def tolerant_network_run(command, *args, **kwargs):
    if isinstance(command, (list, tuple)) and str(command[0]) in pinned_network_executables and kwargs.get("timeout") == 30:
        kwargs["timeout"] = 90
    return original_run(command, *args, **kwargs)
transport.subprocess.run = tolerant_network_run

# Cleanup retains the original generated-path guard and exact rm/rmdir actions,
# but uses one authenticated connection, avoiding a second fragile handshake.
import shlex
import laptop_pull_backup as receiver
from pathlib import PurePosixPath
def single_connection_cleanup(args, remote):
    path = PurePosixPath(remote)
    directory = str(path.parent)
    if path.name != "source.py" or not transport.REMOTE_HELPER_DIR_RE.fullmatch(directory):
        raise ValueError("refusing to remove unexpected remote helper path")
    command = "rm -- " + shlex.quote(remote) + " && rmdir -- " + shlex.quote(directory)
    result = transport.subprocess.run(transport.ssh_command(args, command), stdin=transport.subprocess.DEVNULL, capture_output=True, timeout=90, check=False)
    if not transport.ssh_result_acceptable(result):
        raise RuntimeError("remote helper cleanup failed: " + result.stderr.decode("utf-8", "replace"))
transport.remove_remote_helper = single_connection_cleanup
receiver.remove_remote_helper = single_connection_cleanup

# Select only the stale control component when the original, current preflight
# independently verifies observation, macro and complete-date inventory current.
# Original post-backup verification still requires all components UP_TO_DATE.
import laptop_backup_scheduled as scheduled
original_status = scheduled.scheduled_status
last_status = [None]
def remember_status(*args, **kwargs):
    result = original_status(*args, **kwargs)
    last_status[0] = result
    return result
scheduled.scheduled_status = remember_status
original_jobs = receiver.backup_jobs
def control_jobs(*args, **kwargs):
    latest, jobs = original_jobs(*args, **kwargs)
    status = last_status[0]
    if not isinstance(status, dict) or any(status.get(key, {}).get("status") != "UP_TO_DATE" for key in ("observation", "macro", "inventory")) or status.get("backfill_required") or status.get("control", {}).get("status") != "STALE":
        raise RuntimeError("Control-only refresh requires fresh original preflight with only control stale")
    selected = [(kind, day) for kind, day in jobs if kind == "control"]
    if selected != [("control", None)]:
        raise RuntimeError("Unexpected control selection")
    return latest, selected
receiver.backup_jobs = control_jobs

code = runner.execute(config, "run", CONFIG_SHA)
print(json.dumps({"early_run_exit_code": code, "natural_trigger": False}), flush=True)
raise SystemExit(code)
