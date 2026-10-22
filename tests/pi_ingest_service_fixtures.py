"""Native-definition controls only; no provider data or runtime acceptance."""
import json

COMMAND_TYPE = "a(sasasttttuii)"
REPO = "/srv/ar-local/AR-local"


def command_json(argv, *, flags=()):
    return json.dumps({"type": COMMAND_TYPE, "data": [[argv[0], argv, list(flags), 0, 0, 0, 0, 0, 0, 0]]})


def ingest_definition_fields(*, queued=False, repo=REPO, user="ar-local"):
    result = {}
    for prefix, manual in (("DAILY", False), ("MANUAL", True)):
        argv = ["/usr/bin/python3", repo + "/pi_daily_sync.py", "--banks-only"]
        if manual:
            argv.append("--force")
        argv.append("--skip-git-sync")
        if queued:
            argv = ["/usr/bin/python3", "/usr/local/lib/shared-pi-queue/pi_shared_queue.py", "run",
                    "--project", "ar-local", "--resource", "ar-local", "--mode", "exclusive",
                    "--cpu-slots", "3", "--wait-timeout", "21600", "--max-runtime", "21600", "--", *argv]
        values = {
            "TYPE": "oneshot", "RESTART": "no", "SEND_SIGKILL": "yes",
            "KILL_MODE": "control-group", "START_TIMEOUT": "13h" if queued else "6h 15min",
            "STOP_TIMEOUT": "15min" if queued else "45s", "USER_JSON": json.dumps({"type": "s", "data": user}),
            "EXEC_JSON": command_json(argv),
            "STOP_POST_JSON": command_json(["/usr/bin/python3", "/usr/local/lib/shared-pi-queue/pi_shared_queue_stop_hook.py"])
                              if queued else command_json(["/usr/bin/systemctl", "start", "ar-local-dashboard.service"],
                                                          flags=["privileged"]),
        }
        result.update({prefix + "_" + key: value for key, value in values.items()})
    return result
