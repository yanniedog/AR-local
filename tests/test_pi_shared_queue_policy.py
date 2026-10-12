from datetime import datetime, timedelta, timezone

import pytest

from pi_shared_queue_policy import admission


NOW = datetime(2026, 10, 11, 3, tzinfo=timezone.utc)  # 14:00 Hobart


def job(name, sequence, *, project="other", resources=None, mode="exclusive",
        age=0, state="waiting", slots=1, duration=300, now=NOW):
    return dict(id=name, sequence=sequence, project=project,
                resources=resources or [project], mode=mode,
                ready_since=(now - timedelta(seconds=age)).isoformat(),
                state=state, cpu_slots=slots, max_duration_seconds=duration)


def test_independent_jobs_can_run_together():
    running = job("running", 1, resources=["mining"], state="running")
    candidate = job("candidate", 2, resources=["simjury"])
    assert admission(candidate, [running, candidate], NOW) == (True, "admitted")


@pytest.mark.parametrize("mode, allowed", [("shared", True), ("exclusive", False)])
def test_shared_readers_and_exclusive_writers(mode, allowed):
    running = job("running", 1, resources=["cache"], mode="shared", state="running")
    candidate = job("candidate", 2, resources=["cache"], mode=mode)
    assert admission(candidate, [running, candidate], NOW)[0] is allowed


@pytest.mark.parametrize("host_on_candidate", [True, False])
def test_host_resource_conflicts_with_every_job(host_on_candidate):
    running = job("running", 1, resources=["mining" if host_on_candidate else "host"], state="running")
    candidate = job("candidate", 2, resources=["host" if host_on_candidate else "simjury"])
    assert admission(candidate, [running, candidate], NOW) == (False, "running-conflict")


def test_fifo_blocks_later_conflicting_job_but_allows_independent_job():
    first = job("first", 1, resources=["cache"])
    later = job("later", 2, resources=["cache"])
    independent = job("independent", 3, resources=["logs"])
    assert admission(later, [first, later], NOW) == (False, "earlier-conflicting-job")
    assert admission(independent, [first, later, independent], NOW)[0]


@pytest.mark.parametrize("age, allowed", [(7199, False), (7200, True), (7201, True)])
def test_ar_priority_starts_at_two_hours(age, allowed):
    first = job("first", 1, resources=["ar-local"])
    ar = job("ar", 2, project="ar-local", age=age)
    assert admission(ar, [first, ar], NOW)[0] is allowed
    assert admission(first, [first, ar], NOW)[0] is not allowed


def test_priority_does_not_preempt_running_job():
    running = job("running", 1, resources=["ar-local"], state="running")
    ar = job("ar", 2, project="ar-local", age=7200)
    assert admission(ar, [running, ar], NOW) == (False, "running-conflict")


def test_aged_ar_reserves_cpu_even_against_disjoint_newcomer():
    ar = job("ar", 1, project="ar-local", age=7200, slots=3)
    newcomer = job("newcomer", 2, resources=["mining"])
    assert admission(newcomer, [ar, newcomer], NOW) == (False, "ar-local-cpu-reservation")
    assert admission(ar, [ar, newcomer], NOW)[0]


def test_all_promoted_shared_ar_jobs_reserve_their_cpu_slots():
    promoted = [job('ar-' + str(index), index, project='ar-local', age=7200, mode='shared') for index in range(3)]
    newcomer = job('newcomer', 4, resources=['mining'])
    assert admission(newcomer, [*promoted, newcomer], NOW) == (False, 'ar-local-cpu-reservation')
    for ar in promoted:
        assert admission(ar, [*promoted, newcomer], NOW)[0]
    assert admission(newcomer, [promoted[0], newcomer], NOW) == (True, 'admitted')


def test_compatible_small_jobs_can_use_spare_cpu_before_ar_ages():
    ar = job("ar", 1, project="ar-local", age=7199, slots=3)
    newcomer = job("newcomer", 2, resources=["mining"])
    assert admission(newcomer, [ar, newcomer], NOW)[0]


def test_cpu_budget_is_enforced():
    running = job("running", 1, project="ar-local", state="running", slots=3)
    candidate = job("candidate", 2, resources=["simjury"])
    assert admission(candidate, [running, candidate], NOW) == (False, "cpu-capacity")


def test_ingest_window_prioritizes_ar_and_reserves_independent_cpu():
    now = datetime(2026, 10, 11, 14, 30, tzinfo=timezone.utc)  # 01:30 next day
    first = job("first", 1, resources=["ar-local"], now=now)
    ar = job("ar", 2, project="ar-local", now=now)
    independent = job("independent", 3, resources=["mining"], now=now)
    assert admission(first, [first, ar], now) == (False, "protected-ingest-window")
    assert admission(ar, [first, ar], now)[0]
    assert admission(independent, [first, ar, independent], now) == (False, "protected-ingest-window")


@pytest.mark.parametrize("minute, duration, allowed", [(0, 1739, True), (0, 1740, False), (15, 840, False)])
def test_pre_ingest_cutoff_uses_declared_duration(minute, duration, allowed):
    now = datetime(2026, 10, 11, 13, minute, tzinfo=timezone.utc)  # 00:mm Hobart
    candidate = job("deploy", 1, resources=["host"], duration=duration, now=now)
    assert admission(candidate, [candidate], now)[0] is allowed


def test_end_of_critical_window_opens_host_access():
    now = datetime(2026, 10, 11, 15, tzinfo=timezone.utc)  # 02:00 Hobart
    candidate = job("deploy", 1, resources=["host"], now=now)
    assert admission(candidate, [candidate], now)[0]


def test_pre_ingest_cutoff_also_reserves_cpu_from_independent_jobs():
    now = datetime(2026, 10, 11, 13, 25, tzinfo=timezone.utc)
    candidate = job("candidate", 1, resources=["mining"], now=now)
    assert admission(candidate, [candidate], now) == (False, "would-cross-ingest-start")


def test_critical_ar_reserves_cpu_without_waiting_two_hours():
    now = datetime(2026, 10, 11, 14, 30, tzinfo=timezone.utc)
    candidate = job("candidate", 1, resources=["mining"], now=now)
    ar = job("ar", 2, project="ar-local", slots=3, now=now)
    assert admission(candidate, [candidate, ar], now) == (False, "protected-ingest-window")


def test_critical_window_reserves_all_slots_before_ingest_registers():
    now = datetime(2026, 10, 11, 14, tzinfo=timezone.utc)
    independent = job("independent", 1, resources=["mining"], now=now)
    assert admission(independent, [independent], now) == (False, "protected-ingest-window")
    ar = job("ar", 2, project="ar-local", slots=3, now=now)
    assert admission(ar, [independent, ar], now) == (True, "admitted")


@pytest.mark.parametrize("second, expected", [
    (28 * 60 + 59, "would-cross-ingest-start"),
    (29 * 60, "would-cross-ingest-start"),
    (30 * 60, "protected-ingest-window"),
])
def test_quiet_window_starts_at_0030(second, expected):
    now = datetime(2026, 10, 11, 13, tzinfo=timezone.utc) + timedelta(seconds=second)
    candidate = job("candidate", 1, resources=["mining"], duration=1, now=now)
    assert admission(candidate, [candidate], now) == (False, expected)


def test_last_bounded_job_may_finish_before_quiet_window():
    now = datetime(2026, 10, 11, 13, 28, 58, tzinfo=timezone.utc)
    candidate = job("candidate", 1, resources=["mining"], duration=1, now=now)
    assert admission(candidate, [candidate], now) == (True, "admitted")


def test_ongoing_ingest_retains_capacity_after_fixed_quiet_window():
    now = datetime(2026, 10, 11, 15, 1, tzinfo=timezone.utc)
    running = job("ingest", 1, project="ar-local", slots=3, state="running", now=now)
    candidate = job("candidate", 2, resources=["mining"], now=now)
    assert admission(candidate, [running, candidate], now) == (False, "cpu-capacity")


@pytest.mark.parametrize("unit", ["ar-local-queue-task-publish.service", "ar-local-ingest-now.service"])
def test_manual_ar_work_is_held_during_quiet_window(unit):
    now = datetime(2026, 10, 11, 13, 30, tzinfo=timezone.utc)
    candidate = dict(job("manual", 1, project="ar-local", now=now), unit=unit)
    assert admission(candidate, [candidate], now) == (False, "protected-ingest-window")


def test_manual_ar_declared_duration_and_grace_cannot_cross_quiet_start():
    now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
    candidate = dict(job("manual", 1, project="ar-local", duration=21600, now=now),
                     unit="ar-local-queue-task-publish.service")
    assert admission(candidate, [candidate], now) == (False, "would-cross-ingest-start")


@pytest.mark.parametrize("unit", ["ar-local-daily.service", "ar-local-daily-watchdog.service"])
def test_exact_daily_unit_starts_at_one_despite_aged_manual_waiter(unit):
    now = datetime(2026, 10, 11, 14, tzinfo=timezone.utc)
    manual = dict(job("manual", 1, project="ar-local", age=7200, now=now),
                  unit="ar-local-queue-task-publish.service")
    daily = dict(job("daily", 2, project="ar-local", slots=3, duration=21600, now=now), unit=unit)
    assert admission(daily, [manual, daily], now) == (True, "admitted")


def test_manual_ar_still_receives_two_hour_priority_outside_quiet_window():
    earlier = job("earlier", 1, resources=["ar-local"])
    manual = dict(job("manual", 2, project="ar-local", age=7200),
                  unit="ar-local-queue-task-publish.service")
    assert admission(manual, [earlier, manual], NOW) == (True, "admitted")


def test_older_promoted_ar_preserves_fifo_between_ar_requests():
    first = job("first", 1, project="ar-local", age=7200)
    later = job("later", 2, project="ar-local", age=7201)
    assert admission(later, [first, later], NOW) == (False, "earlier-conflicting-job")


@pytest.mark.parametrize("change", [
    {"project": "../unsafe"}, {"resources": []}, {"resources": ["host", "host"]},
    {"cpu_slots": 4}, {"cpu_slots": True}, {"max_duration_seconds": 1801},
    {"ready_since": "2026-10-11T03:00:01Z"}, {"ready_since": "2026-10-11T03:00:00"},
    {"state": "done"}, {"sequence": -1},
])
def test_bad_candidate_fails_closed(change):
    candidate = job("candidate", 1)
    candidate.update(change)
    assert admission(candidate, [candidate], NOW) == (False, "invalid-state")


def test_long_ingest_is_allowed_only_for_ar_local():
    ar = job("ar", 1, project="ar-local", duration=21600)
    assert admission(ar, [ar], NOW)[0]
    ar["max_duration_seconds"] = 21601
    assert admission(ar, [ar], NOW) == (False, "invalid-state")


def test_bad_other_record_duplicate_sequence_and_mismatched_candidate_fail_closed():
    candidate = job("candidate", 2)
    bad = job("bad", 1)
    bad["state"] = "invalid"
    assert admission(candidate, [candidate, bad], NOW) == (False, "invalid-state")
    assert admission(candidate, [candidate, job("duplicate", 2)], NOW) == (False, "invalid-state")
    assert admission(candidate, [dict(candidate, resources=["different"])], NOW) == (False, "invalid-state")


def test_running_candidate_and_naive_clock_are_denied():
    candidate = job("candidate", 1, state="running")
    assert admission(candidate, [candidate], NOW) == (False, "already-running")
    assert admission(candidate, [candidate], NOW.replace(tzinfo=None)) == (False, "invalid-state")


@pytest.mark.parametrize('date,utc_hours', [('2026-04-05', 25), ('2026-10-04', 23)])
def test_dst_transition_keeps_next_quiet_window_at_calendar_0030(date, utc_hours):
    from zoneinfo import ZoneInfo
    from pi_shared_queue_policy import _protected
    start = datetime.fromisoformat(date).replace(hour=0, minute=30,
                                                tzinfo=ZoneInfo('Australia/Hobart'))
    critical, next_start = _protected(start)
    assert critical
    assert next_start.hour == 0 and next_start.minute == 30
    assert next_start.date() == start.date() + timedelta(days=1)
    assert (next_start.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() == utc_hours * 3600


@pytest.mark.parametrize('running', [False, True])
def test_conflicting_promoted_reservations_do_not_consume_multiple_slots(running):
    ar = [job('ar-' + str(i), i, project='ar-local', age=7200,
              mode='exclusive', state='running' if running and i == 0 else 'waiting') for i in range(3)]
    candidate = job('independent', 4, resources=['mining'])
    assert admission(candidate, [*ar, candidate], NOW) == (True, 'admitted')


@pytest.mark.parametrize('running_slots,promoted_slots', [(1, 3), (2, 2)])
def test_promoted_cpu_reservation_blocks_new_arrivals_while_running_work_drains(
        running_slots, promoted_slots):
    running = job('running', 1, resources=['other-running'], state='running', slots=running_slots)
    promoted = job('promoted', 2, project='ar-local', age=7200, slots=promoted_slots)
    newcomer = job('newcomer', 3, resources=['other-new'])
    records = [running, promoted, newcomer]
    assert admission(promoted, records, NOW) == (False, 'cpu-capacity')
    assert admission(newcomer, records, NOW) == (False, 'ar-local-cpu-reservation')
    assert admission(promoted, [promoted, newcomer], NOW) == (True, 'admitted')
