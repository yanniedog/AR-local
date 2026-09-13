# Pi GitHub incident reporting

The Pi reports Drive authentication/access failures and failed, incomplete or
missed ingests directly to the AR-local GitHub repository. This is independent
of Codex, the laptop, SMTP, and whether the Drive backup timers are enabled.
Existing email alerts and GitHub's publication watchdog remain in place.

`ar-local-issue-watchdog.timer` runs on a five-minute calendar schedule and after
boot, independently of whether the preceding service run succeeded. It checks:

- A fresh Google OAuth refresh using the exact private rclone configuration.
- Available Drive storage, the uniquely resolved configured repository folder,
  permission to add files, and an actual read of its existing Restic config.
- Whether the scheduled 01:00 Hobart ingest started, after a 30-minute grace.
- Current finalization metadata: missing/invalid, partial, or complete.
- An ingest that remains active for more than six hours.
- Existing backup failures, including ones that occurred before alerts were
  installed. Backup recovery requires the accepted resource/request binding;
  a process exiting zero alone cannot close a backup incident.

A backup refused before worker startup in the ingest quiet window is recorded
as `QUIET_WINDOW_DEFERRED` only when its exact service PID/start binds a unique
current request and a clean resource receipt containing that precise refusal.
This does not close an earlier incident. Other exit2 reasons, missing proof,
failed cleanup and interruptions after work starts remain alertable.

OnFailure drop-ins additionally trigger immediate reporting for the daily
ingest, manual ingest, ingest watchdog, and Drive backup services. They append
to existing failure handlers. A watchdog failure is distinct from an ingest
failure: it may involve publication or recovery supervision.

Drive network probes yield during 00:30–03:30 Hobart and while ingest is active.
Ingest failure alerts and queued GitHub delivery still operate in that window.
The probe reads metadata and the encrypted repository config only. It never
writes or deletes cloud files, changes credentials, starts an ingest/backup, or
claims that upload/restore verification has completed. Write permission is
checked through Drive capabilities, not by uploading a test backup.

## Delivery and privacy

Each condition has a stable hidden issue marker. Continued failures reuse its
issue; recovery closes it, and recurrence reopens it. Different ingest dates
have distinct incidents. A failure that recovers while GitHub is unavailable
is still reported and closed once delivery resumes. A reopened issue labels its
retained historical recovery time as "Last recovery"; it is not current recovery.

Private incident state is committed and fsynced before network delivery. Failed
delivery remains pending for the next calendar tick. `QUEUED` still returns a
nonzero exit status so delivery failure remains visible. Direct issue enumeration
reconciles
an ambiguous issue creation without relying on delayed search indexing. If that
enumeration cannot complete within its bounds, delivery remains pending rather
than creating a possible duplicate. Concurrent updates retain their newer pending
revision. GitHub calls have separate native process deadlines and do not forward
credentials through redirects or inherited proxies.

Public issue bodies contain fixed categories and observation timestamps. They
exclude raw provider errors, journal text, configuration files and credentials.
The GitHub token needs Issues read/write access on the selected repository.
Neither local reporting nor queued delivery can reach GitHub while the Pi is
offline or its GitHub credentials are invalid; the existing GitHub-hosted
publication watchdog provides an independent stale-payload signal.

## Controlled installation

Install from the exact reviewed, tested immutable component checkout. This
component can run separately from the dashboard/ingest checkout: it never
activates unaccepted producer changes or edits source observations. Retain an
installation inventory, previous unit/drop-in bytes, commit/hash identity,
focused Pi test results, live read-only checks and actual issue-delivery proof.

```sh
sudo bash deploy/pi/install-issue-alerts.sh /path/to/approved/AR-local pi /srv/ar-local/data /var/lib/ar-local-alerts
```

The installer renders and verifies the three new units before installing them,
adds only its named failure drop-ins, and reloads systemd. It does not start or
restart the dashboard, ingest, or backup, and does not enable any timer.

The services load `/etc/ar-local/app-payload.env` for an existing GitHub token,
`/etc/ar-local/drive-backup.env` for Drive locations, and optional
`/etc/ar-local/issue-alerts.env` for a dedicated Issues token or repository
override. Keep any token-bearing file root-owned mode0600. Supported settings:

```text
AR_LOCAL_ALERT_REPOSITORY=yanniedog/AR-local
GH_TOKEN=<private token with Issues read/write permission>
```

The supported deployment uses an immutable runtime below `/srv` and a private
Drive configuration below `/var/lib`; `ProtectHome=true` remains enabled. The
repository must name the dedicated `drive.file` remote and exact relative folder
components, without leading/trailing/repeated slashes. Unsupported locations or
noncanonical repository spelling fail closed rather than selecting another tree.

Run `pi_issue_watchdog.py --checks-only` under the exact service environment to
inspect current health without creating incidents/issues. Then execute the
normal service once and verify real incident delivery/deduplication. When no
incident exists, an explicitly identified `--delivery-test` can create and close
one verification issue. It cannot be combined with `--checks-only`.

After these checks pass, enable only the alert timer:

```sh
sudo systemctl enable --now ar-local-issue-watchdog.timer
```

The alert spool is independent of the backup spool. Preserve its incident state
across updates. Alert deployment does not enable the still-uncommissioned Drive
backup timers or satisfy backup/restore acceptance.

References: [Google token refresh](https://developers.google.com/identity/protocols/oauth2/web-server#offline),
[Drive file capabilities](https://developers.google.com/workspace/drive/api/reference/rest/v3/files),
[GitHub Issues API](https://docs.github.com/en/rest/issues/issues).
