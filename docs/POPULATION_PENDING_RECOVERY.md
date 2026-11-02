# Current-day population recovery with historical uploads pending

A queue can contain an older withheld publication and the selected current-day
population hold. Requiring either an exclusively historical queue or an
exclusively current-day queue prevented the prerequisite provider recovery.

The narrow exception admits exactly one verified current-day observation among
valid, distinct, strictly older source pointers. Ambiguous identities, future
sources, selection retries and malformed metadata still defer. This admission
does not change daily claims, probe/capture budgets, cooldowns or population proof.
A failed or empty provider response cannot clear a membership hold.

After recovery, supersession requires the selected same-day child, its exact
parent event/contract and reconciled baseline. An immutable audit receipt retains
the entire preceding queue and explicitly records that publication is unconfirmed.
Only the predecessor's slot is replaced; historical pointers and their order stay
intact. An already-queued exact successor is consolidated only after this proof.

The daily worker can retry the verified publishable current source by its exact
publication source key. A missing source or cooldown cannot fall back to an older
upload. Successful publication removes only that source; failed, withheld or
interrupted publication leaves it pending. None of these transitions asserts that
historical uploads succeeded or promotes unverified population data.
