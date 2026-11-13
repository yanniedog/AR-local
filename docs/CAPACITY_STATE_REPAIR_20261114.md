# Capacity monitor follow-up — 2026-11-14

Late review of merged #1133 found recoverable notification-state gaps. This
follow-up starts from #1137 merge `905362e`; it changes no Pi service, credentials,
schedule, ingest data, retention policy or production configuration.

- Serialize the complete monitor state transaction with the existing kernel file
  lock, including assessment, delivery reservation and final outcome. Use the
  existing unique-temp, fsynced atomic JSON writer. This lock is monitor-specific;
  daily ingest has no dependency on it.
- Preserve an unexpired delivery retry reservation across temporary SMTP
  unconfiguration. Repeated monitor invocations cannot contact SMTP early.
- Record `ValueError` and `OverflowError` as failed delivery outcomes without
  exposing exception text, while retaining the current capacity assessment.
- Return a failed notification result when an alert is requested but SMTP is
  unconfigured. Sampling without `--notify` remains successful independently.
- Strengthen the saved-assessment test and exercise concurrent delivery,
  configuration errors, retry continuity and non-notifying sampling.

SMTP cannot provide exactly-once delivery across an ambiguous disconnect or
process crash after relay acceptance. The monitor retains its existing bounded
retry policy; it does not claim an unknown outcome was delivered or permanently
suppress a potentially undelivered critical alert. The duplicate-delivery review
suggestion is declined on that basis; #1133 already reduced retry frequency and
did not introduce SMTP ambiguity. SMTP setup remains operator-deferred.

Validation: 12 focused tests passed through the isolated Windows runner. The
first invocation included a nonexistent atomic test filename and collected no
tests; its failed receipt is retained. No SMTP message was sent. Exact-head CI,
review and runtime acceptance remain separate gates.
