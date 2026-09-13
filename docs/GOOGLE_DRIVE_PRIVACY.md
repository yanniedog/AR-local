# AR-local Pi Backups privacy policy

Effective 13 September 2026.

AR-local Pi Backups is the repository owner's personal database backup tool.
Its purpose is to preserve and restore AR-local CDR data in the owner's Google
Drive. See the [backup documentation](GOOGLE_DRIVE_BACKUP.md) and
[terms of use](GOOGLE_DRIVE_TERMS.md).

## Google data access and use

The tool requests only Google's `drive.file` permission. It creates its own
backup folder and reads and writes the files available to this application
under that permission. It uses their contents and metadata to upload backups,
find existing encrypted chunks, check repository integrity and restore data.
It does not request access to Gmail, contacts or the rest of the owner's Drive.

The backup contains retained CDR databases, source responses, observations,
ingest logs, audit records and non-secret recovery instructions. Credentials,
encryption passwords and identified secret-bearing configuration files are
excluded. Restic compresses and encrypts backup content on the Pi before
uploading it to Google Drive. Google processes the stored objects and account
and API request metadata as the storage provider.

## Storage, sharing and retention

OAuth credentials are stored in private files on the owner's Pi for unattended
access. The encryption password is stored separately, with an owner-controlled
recovery copy outside the Pi. Private local diagnostics may contain provider
identifiers and are not intended for publication.

The backup application does not sell Google user data, use it for advertising,
train AI models with it or send it to another backup service. It does not
publish or share Drive backup files. Access remains subject to the owner's
Google account and any sharing changes the owner makes independently.

Backup snapshots and audit evidence are retained until the owner removes them.
There is no automatic pruning. Restores create private working copies on the
owner's system; the backup documentation describes their verification.

## Owner control and contact

The owner can stop the Pi backup services and revoke the application's access
in [Google Account connections](https://myaccount.google.com/connections).
Revocation stops further authorized access but does not delete stored backups.
The owner can remove the backup folder through Google Drive and remove local
credentials or working copies separately. Removing the only encryption key
makes encrypted backups unrecoverable.

For questions, contact the repository maintainer through
[the AR-local project](https://github.com/yanniedog/AR-local). Do not post tokens,
passwords, private logs or backup content in public issues.
