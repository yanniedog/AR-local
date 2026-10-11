# Ingest failure notifications

An ingest incident must not be considered reported merely because a service
failed, a GitHub issue exists, or a public payload is current. Capture,
publication, monitor availability and delivery are separate observations.

## Detection

The existing `pi-ingest-watchdog` GitHub Actions workflow checks the public
publication independently of the Pi and the home router. It uses the shared
01:00 Australia/Hobart schedule and publication grace period. Its issue and
artifact describe the public ciphertext receipt scope; this cannot certify
complete provider capture. Scheduled Actions can be delayed or dropped, so
the configured interval is not a detection deadline or availability guarantee.
The workflow also retains exact-date Pi ingest, missed-start and watchdog
incidents already reported to GitHub. These remain actionable even when the
public receipt is current. They are previously reported evidence, not proof
of fresh Pi reachability. Publication recovery cannot close those incidents.
Checks run at minutes 17 and 47, with one serialized workflow and a ten-minute
timeout. A new or materially changed incident escalates the workflow once.
An unchanged known failure retains `attention_required=true`, a warning and
the evidence artifact, while the monitoring process may succeed. A green
monitor run therefore does not mean the ingest is healthy. Infrastructure
and incident-delivery failures still fail the workflow.

`python scripts/ingest_notification_snapshot.py` is a separate read-only
observation for a notification controller with Pi network access. It checks
the three ingest units, bounded finalization metadata and recovery summary,
and independently checks the public receipt. It does not ingest, publish,
repair a lock, inspect database contents, probe Drive or send notifications.
Unreachable or malformed evidence is unknown and actionable, never healthy.
The result separates failed attempts, missing starts, partial capture,
publication failures and monitoring failures. A current publication does not
cancel a partial-capture incident.
Pending publication dates include queued entries beneath an older queue head.
A recovered attempt remains recorded separately from an ongoing failure.
This bounded observation does not prove that the selected capture generation
is exactly the generation in the public ciphertext.
The optional `failure_counts` are bound to the selected finalized generation,
contract and ingest-status hash. Reads are capped; incomplete provenance or a
changed pointer yields unavailable counts. Product identities are distinct
within provider identity. Listing failures leave unknown product populations,
so the known-product count is explicitly marked as a lower bound.

## Daily delivery identity

Use `AR-INGEST-YYYY-MM-DD`, in Australia/Hobart, as the notification envelope
for a failed observation date. Coalesce the day's failure reasons. Keep old
historical gaps in their original records; do not produce a new failure email
every day solely because an old source capture cannot be recovered.

A connected-account controller must serialize each run and retain a durable
per-channel record outside the source checkout. Record an attempt before
calling a provider, then retain its message, event or issue identifier. After
an ambiguous response, reconcile the exact incident marker at that provider
before sending again. An unknown outcome is not a delivered receipt.

For each newly failed date:

1. Send one direct email to the configured recipient containing the incident
   identity. Published partial capture gets an ordinary notification. Reserve
   `URGENT`, IMPORTANT and STARRED for a completely failed or missed ingest or
   usable dated payload. An unreachable Pi is uncertainty; independently check
   publication before claiming absence. Internet or power loss are possible
   causes, not a diagnosis. Read the exact message back and verify INBOX; for
   urgent failures verify the controller's priority labels too. The Gmail
   connector does not expose arbitrary SMTP priority headers; a subject or
   Important label cannot guarantee a phone push or that the user read it.
2. Create one private, nonrecurring calendar event at the operator's evening
   time (20:00 Australia/Hobart), with a popup reminder. Search for the exact incident marker before
   creation. Reuse the existing event for subsequent status updates. If first
   detected after the evening time, place it at that time the following day
   and retain the original incident identity in the description. Do not add
   guests or conferencing. For a published payload, the watch-friendly title is
   `AR Ingest ok: P/V failed (products/providers)` using unique failed products
   and affected providers. Failed listing requests may leave product counts
   unknown: show a lower bound such as `15+/8`, never relabel requests as
   products or infer zero. Use `?` for unavailable counts. If the dated usable
   payload is verified absent, the entire title is `AR FAILED INGEST!`. Unknown
   publication uses `AR INGEST UNVERIFIED`. Keep the incident key out of the title.
3. Retain the corresponding GitHub issue/inbox notification. Repeated public
   checks must not create duplicate issues or identical comments. GitHub email
   and mobile delivery depend on the account's notification settings.
4. Report a new failure, recovery or failed notification channel in the
   controller chat. Stay quiet for unchanged, already-reported failures and
   healthy checks. Do not hide failed delivery as an ordinary quiet check.

Record channel outcomes independently. If one provider is unavailable, attempt
the other authorized channels. Never mark all channels delivered because one
succeeded. One accepted failure email per date is the policy; do not blindly
retry an ambiguous email request. Recovery updates the same incident/calendar
entry without sending another failure email. Severity changes may update the
existing email's controller-added priority labels, never create another email.

## Availability and commissioning

Connected Gmail and Calendar tools are not SMTP credentials for a GitHub
runner. A local Codex scheduled controller requires the computer and app to
remain available. Keep the external GitHub check independent, and report this
local dependency explicitly. Complete offsite direct delivery requires a
separately commissioned hosted controller or mail/calendar credentials; do
not claim that a local controller supplies this.

The Pi's old SMTP configuration must be verified as real credentials, not
merely nonempty strings. In the October 11 incident its username, password and
sender still matched the example placeholders. Do not copy placeholders into
a cloud secret, print credentials, or claim SMTP works without a real send and
recipient readback. This workflow does not modify or depend on that SMTP path.

Commission with operational tests for grace periods and DST, failed and
partial capture, unreachable Pi, invalid receipts, duplicate observations,
ambiguous submission and independent channel failure. Actual mailbox readback
and calendar event/reminder readback are separate from synthetic tests.
Future scheduled execution and phone display remain unverified until observed.
