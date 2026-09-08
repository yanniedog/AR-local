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
if now.date().isoformat() != "2026-09-09" or now.hour != 5:
    raise RuntimeError("One-time early-start authorization has expired")
attempt = Path(__file__).with_name("early-start-authority.json")
with attempt.open("x", encoding="utf-8") as stream:
    json.dump({"user_instruction": "Do it now rather than 6am.",
               "at": now.isoformat(), "config_sha256": CONFIG_SHA,
               "installed_source_sha256": SOURCE_SHA,
               "wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "scope": "One invocation before 06:00 September 9; ordinary token, identity, locks, quiet-window and receiver preflight retained",
               "natural_trigger": False}, stream, indent=2)

def authorized_start(instant):
    local = instant.astimezone(runner.HOBART)
    return local.date().isoformat() == "2026-09-09" and local.hour == 5

# Only this process's scheduling predicate changes. execute retains all remaining
# installed checks and holds the same whole-job lock; scheduled.main also keeps
# its separate quiet-window, production identity and source validation checks.
runner.allowed_start = authorized_start
code = runner.execute(config, "run", CONFIG_SHA)
print(json.dumps({"early_run_exit_code": code, "natural_trigger": False}), flush=True)
raise SystemExit(code)
