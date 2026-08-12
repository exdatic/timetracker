"""Tests for the ported domain logic."""

from __future__ import annotations

from datetime import date, datetime
import os
import time

import pytest

from timetracker.domain.duration import (
    HOUR_MS,
    MINUTE_MS,
    format_duration,
    format_timer,
    map_duration,
    parse_duration,
)
from timetracker.domain.goals import compute_progress, is_active_today
from timetracker.domain.ranges import (
    RangeLength,
    day_range,
    format_range,
    get_range,
    split_into_days,
    start_of_day,
    shift_timestamp,
    to_ms,
)
from timetracker.domain.statistics import (
    duration_in_range,
    get_statistics,
    group_by_activity,
    group_by_category,
    group_by_tag,
    records_in_range,
)
from timetracker.domain.untracked import (
    calculate_untracked_ranges,
    get_untracked_records,
    uncovered_ranges,
)
from timetracker.models import (
    Goal,
    GoalRange,
    GoalSubtype,
    GoalType,
    Range,
    Record,
    RunningRecord,
)


def ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return to_ms(datetime(year, month, day, hour, minute))


DAY = ms(2026, 3, 10)  # a Tuesday


# --------------------------------------------------------------------------- #
# Duration
# --------------------------------------------------------------------------- #


def test_format_duration():
    assert format_duration(90 * MINUTE_MS) == "1h 30m"
    assert format_duration(90 * MINUTE_MS + 15_000) == "1h 30m 15s"
    assert format_duration(45_000) == "45s"
    assert format_duration(45_000, show_seconds=False) == "0m"
    assert format_duration(0) == "0s"


def test_format_timer():
    assert format_timer(HOUR_MS + 2 * MINUTE_MS + 3_000) == "1:02:03"


def test_map_duration_drops_seconds_when_hidden():
    assert map_duration(0, 90_500, show_seconds=True) == 90_500
    assert map_duration(0, 90_500, show_seconds=False) == 60_000
    assert map_duration(100, 0) == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1h 30m", 90 * MINUTE_MS),
        ("90m", 90 * MINUTE_MS),
        ("1:30", 90 * MINUTE_MS),
        ("45", 45 * MINUTE_MS),
        ("2h", 2 * HOUR_MS),
        ("", None),
        ("nonsense", None),
    ],
)
def test_parse_duration(text, expected):
    assert parse_duration(text) == expected


# --------------------------------------------------------------------------- #
# Ranges
# --------------------------------------------------------------------------- #


def test_day_range_covers_exactly_one_day():
    result = get_range(RangeLength.DAY, now=DAY + 13 * HOUR_MS)
    assert result == Range(DAY, ms(2026, 3, 11))


def test_day_range_shift_moves_backwards():
    result = get_range(RangeLength.DAY, shift=-2, now=DAY + HOUR_MS)
    assert result == Range(ms(2026, 3, 8), ms(2026, 3, 9))


def test_week_range_respects_first_day_of_week():
    monday = get_range(RangeLength.WEEK, first_day_of_week=0, now=DAY)
    assert monday == Range(ms(2026, 3, 9), ms(2026, 3, 16))

    sunday = get_range(RangeLength.WEEK, first_day_of_week=6, now=DAY)
    assert sunday == Range(ms(2026, 3, 8), ms(2026, 3, 15))


def test_month_and_year_ranges():
    assert get_range(RangeLength.MONTH, now=DAY) == Range(ms(2026, 3, 1), ms(2026, 4, 1))
    assert get_range(RangeLength.YEAR, now=DAY) == Range(ms(2026, 1, 1), ms(2027, 1, 1))


def test_month_range_wraps_the_year():
    december = ms(2026, 12, 20)
    assert get_range(RangeLength.MONTH, now=december) == Range(ms(2026, 12, 1), ms(2027, 1, 1))


def test_all_range_is_undefined():
    assert get_range(RangeLength.ALL, now=DAY).is_undefined


def test_last_days_range_ends_after_today():
    result = get_range(RangeLength.LAST, last_days=7, now=DAY + 5 * HOUR_MS)
    assert result == Range(ms(2026, 3, 4), ms(2026, 3, 11))


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset is unavailable")
def test_calendar_ranges_preserve_day_boundaries_across_dst(monkeypatch):
    """Parity with Android TimeMapper's Calendar.DATE arithmetic."""
    previous = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Europe/Berlin")
    time.tzset()
    try:
        spring_day = day_range(date(2026, 3, 29))
        assert spring_day.duration == 23 * HOUR_MS

        shifted_spring_day = day_range(date(2026, 3, 29), 4 * HOUR_MS)
        assert datetime.fromtimestamp(shifted_spring_day.time_started / 1000).hour == 4

        result = get_range(
            RangeLength.LAST,
            last_days=7,
            now=to_ms(datetime(2026, 3, 31, 12)),
        )
        assert result == Range(
            to_ms(datetime(2026, 3, 25)),
            to_ms(datetime(2026, 4, 1)),
        )
        assert result.duration == 7 * 24 * HOUR_MS - HOUR_MS
    finally:
        if previous is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", previous)
        time.tzset()


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset is unavailable")
@pytest.mark.parametrize(
    ("start_hour", "shift_hours", "expected_hour"),
    [
        (0, 1, 1),
        (0, 2, 3),
        (0, 3, 3),
        (5, -2, 3),
        (5, -3, 1),
        (5, -5, 0),
    ],
)
def test_shift_timestamp_android_dst_forward_vectors(
    monkeypatch, start_hour, shift_hours, expected_hour
):
    """Representative vectors from Android CalendarShiftTest."""
    previous = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Europe/Berlin")
    time.tzset()
    try:
        start = to_ms(datetime(2025, 3, 30, start_hour))
        shifted = shift_timestamp(start, shift_hours * HOUR_MS)
        assert datetime.fromtimestamp(shifted / 1000).hour == expected_hour
    finally:
        if previous is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", previous)
        time.tzset()


def test_start_of_day_shift_moves_the_boundary():
    shift = 4 * HOUR_MS
    # 02:00 still belongs to the previous day when the day starts at 04:00.
    assert start_of_day(DAY + 2 * HOUR_MS, shift) == ms(2026, 3, 9) + shift
    assert start_of_day(DAY + 5 * HOUR_MS, shift) == DAY + shift


def test_range_title_uses_logical_date_with_negative_day_shift():
    shift = -4 * HOUR_MS
    time_range = get_range(RangeLength.DAY, now=DAY + HOUR_MS, start_of_day_shift=shift)
    assert format_range(RangeLength.DAY, time_range, shift) == "Tue, 10 Mar 2026"


def test_negative_day_shift_keeps_logical_week_month_and_year():
    """Port of TimeMapper boundary cases where the boundary is on the prior date."""
    shift = -4 * HOUR_MS
    now = ms(2026, 4, 1, 1)

    assert get_range(RangeLength.WEEK, now=now, start_of_day_shift=shift) == Range(
        ms(2026, 3, 30) + shift,
        ms(2026, 4, 6) + shift,
    )
    assert get_range(RangeLength.MONTH, now=now, start_of_day_shift=shift) == Range(
        ms(2026, 4, 1) + shift,
        ms(2026, 5, 1) + shift,
    )
    assert get_range(RangeLength.YEAR, now=now, start_of_day_shift=shift) == Range(
        ms(2026, 1, 1) + shift,
        ms(2027, 1, 1) + shift,
    )


def test_split_into_days():
    days = split_into_days(Range(DAY + 20 * HOUR_MS, ms(2026, 3, 12) + 3 * HOUR_MS))
    assert [d.time_started for d in days] == [
        DAY + 20 * HOUR_MS,
        ms(2026, 3, 11),
        ms(2026, 3, 12),
    ]
    assert days[-1].time_ended == ms(2026, 3, 12) + 3 * HOUR_MS


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="tzset is unavailable")
def test_split_into_days_keeps_shifted_boundaries_after_dst(monkeypatch):
    previous = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Europe/Berlin")
    time.tzset()
    try:
        shift = 2 * HOUR_MS
        first = day_range(date(2026, 3, 29), shift)
        last = day_range(date(2026, 3, 31), shift)

        days = split_into_days(Range(first.time_started, last.time_started), shift)

        assert [item.time_started for item in days] == [
            day_range(date(2026, 3, 29), shift).time_started,
            day_range(date(2026, 3, 30), shift).time_started,
        ]
        assert days[-1].time_ended == last.time_started
    finally:
        if previous is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", previous)
        time.tzset()


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #


def record(type_id: int, start_hour: float, hours: float, day: int = DAY, tags=None) -> Record:
    start = day + int(start_hour * HOUR_MS)
    return Record(
        id=int(start / 1000) % 1_000_000,
        type_id=type_id,
        time_started=start,
        time_ended=start + int(hours * HOUR_MS),
        tag_ids=tags or [],
    )


def test_records_in_range_uses_overlap_not_containment():
    day_range = Range(DAY, ms(2026, 3, 11))
    crossing_midnight = record(1, 23, 3)  # 23:00 – 02:00
    assert records_in_range([crossing_midnight], day_range) == [crossing_midnight]

    next_day = Range(ms(2026, 3, 11), ms(2026, 3, 12))
    assert records_in_range([crossing_midnight], next_day) == [crossing_midnight]


def test_duration_in_range_clamps_records_to_the_range():
    day_range = Range(DAY, ms(2026, 3, 11))
    crossing_midnight = record(1, 23, 3)
    assert duration_in_range([crossing_midnight], day_range) == HOUR_MS


def test_duration_over_all_records_is_not_clamped():
    crossing_midnight = record(1, 23, 3)
    assert duration_in_range([crossing_midnight], Range(0, 0)) == 3 * HOUR_MS


def test_statistics_are_grouped_and_sorted_by_duration():
    records = [record(1, 9, 2), record(1, 14, 1), record(2, 18, 4)]
    day_range = Range(DAY, ms(2026, 3, 11))

    result = get_statistics(day_range, group_by_activity(records))

    assert [(s.id, s.duration, s.count) for s in result] == [
        (2, 4 * HOUR_MS, 1),
        (1, 3 * HOUR_MS, 2),
    ]


def test_group_by_category_counts_a_record_once_per_category():
    records = [record(1, 9, 2)]
    grouped = group_by_category(records, {1: [10, 11]})
    assert set(grouped) == {10, 11}


def test_group_by_category_falls_back_to_uncategorized():
    grouped = group_by_category([record(1, 9, 2)], {}, uncategorized_id=-2)
    assert list(grouped) == [-2]


def test_group_by_tag_splits_multi_tagged_records():
    grouped = group_by_tag([record(1, 9, 2, tags=[5, 6]), record(2, 12, 1)], untagged_id=-2)
    assert set(grouped) == {5, 6, -2}


@pytest.mark.parametrize("group", ["category", "tag"])
def test_untracked_is_not_grouped_with_uncategorized_or_untagged(group):
    tracked = record(1, 9, 1)
    untracked = record(-1, 10, 1)

    if group == "category":
        grouped = group_by_category([tracked, untracked], {}, uncategorized_id=-2)
    else:
        grouped = group_by_tag([tracked, untracked], untagged_id=-2)

    assert grouped[-2] == [tracked]
    assert grouped[-1] == [untracked]


# --------------------------------------------------------------------------- #
# Untracked time
# --------------------------------------------------------------------------- #


def test_uncovered_ranges_finds_the_gaps():
    gaps = uncovered_ranges(0, 100, [Range(10, 20), Range(40, 60)])
    assert gaps == [Range(0, 10), Range(20, 40), Range(60, 100)]


def test_uncovered_ranges_merges_overlapping_records():
    gaps = uncovered_ranges(0, 100, [Range(10, 50), Range(20, 60), Range(55, 70)])
    assert gaps == [Range(0, 10), Range(70, 100)]


def test_uncovered_ranges_with_full_coverage_is_empty():
    assert uncovered_ranges(0, 100, [Range(-10, 200)]) == []


# Ported from Android's complete UnCoveredRangesMapperTest parameter table.
@pytest.mark.parametrize(
    ("start", "end", "segments", "expected"),
    [
        (10, 0, [Range(2, 3)], []),
        (0, 0, [Range(2, 3)], []),
        (0, 0, [], []),
        (0, 10, [], [Range(0, 10)]),
        (0, 10, [Range(2, 2)], [Range(0, 2), Range(2, 10)]),
        (0, 10, [Range(0, 0), Range(5, 5), Range(10, 10)], [Range(0, 5), Range(5, 10)]),
        (0, 10, [Range(0, 10)], []),
        (0, 10, [Range(0, 2), Range(8, 10)], [Range(2, 8)]),
        (0, 10, [Range(0, 6), Range(4, 10)], []),
        (0, 10, [Range(0, 5), Range(5, 10)], []),
        (0, 10, [Range(2, 3)], [Range(0, 2), Range(3, 10)]),
        (0, 10, [Range(3, 2)], [Range(0, 2), Range(3, 10)]),
        (0, 10, [Range(0, 2)], [Range(2, 10)]),
        (0, 10, [Range(7, 10)], [Range(0, 7)]),
        (0, 10, [Range(2, 3), Range(2, 3)], [Range(0, 2), Range(3, 10)]),
        (0, 10, [Range(2, 3), Range(2, 4)], [Range(0, 2), Range(4, 10)]),
        (0, 10, [Range(3, 2), Range(2, 4)], [Range(0, 2), Range(4, 10)]),
        (0, 10, [Range(2, 4), Range(4, 2)], [Range(0, 2), Range(4, 10)]),
        (0, 10, [Range(2, 5), Range(1, 6)], [Range(0, 1), Range(6, 10)]),
        (0, 10, [Range(2, 5), Range(4, 8)], [Range(0, 2), Range(8, 10)]),
        (0, 10, [Range(1, 2), Range(2, 4), Range(4, 7)], [Range(0, 1), Range(7, 10)]),
        (0, 10, [Range(0, 3), Range(3, 6), Range(6, 10)], []),
        (0, 10, [Range(2, 5), Range(8, 9)], [Range(0, 2), Range(5, 8), Range(9, 10)]),
        (0, 10, [Range(0, 5), Range(8, 10)], [Range(5, 8)]),
        (10, 20, [Range(5, 6)], [Range(10, 20)]),
        (10, 20, [Range(4, 6), Range(24, 26)], [Range(10, 20)]),
        (10, 20, [Range(4, 16)], [Range(16, 20)]),
        (10, 20, [Range(4, 14), Range(16, 26)], [Range(14, 16)]),
        (10, 20, [Range(4, 16), Range(14, 26)], []),
    ],
)
def test_uncovered_ranges_android_vectors(start, end, segments, expected):
    assert uncovered_ranges(start, end, segments) == expected


def test_untracked_respects_the_short_gap_cutoff():
    ranges = calculate_untracked_ranges(
        records=[Range(0, 10_000), Range(15_000, 100_000)],
        time_range=Range(0, 100_000),
        min_start=0,
        max_end=100_000,
        duration_cutoff_seconds=10,
    )
    assert ranges == []  # the 5 second gap is ignored


def test_untracked_starts_at_the_first_record_and_stops_at_now():
    now = DAY + 12 * HOUR_MS
    records = [record(1, 9, 1)]  # 09:00 – 10:00
    untracked = get_untracked_records(
        time_range=Range(DAY, ms(2026, 3, 11)),
        records=[r.range for r in records],
        first_record_start=records[0].time_started,
        now=now,
    )
    assert [(r.time_started, r.time_ended) for r in untracked] == [(DAY + 10 * HOUR_MS, now)]


def test_no_untracked_time_without_records():
    assert get_untracked_records(Range(DAY, DAY + HOUR_MS), [], None, DAY + HOUR_MS) == []


# --------------------------------------------------------------------------- #
# Goals
# --------------------------------------------------------------------------- #


def daily_goal(value: int, subtype: GoalSubtype = GoalSubtype.GOAL) -> Goal:
    return Goal(id=1, range=GoalRange.DAILY, type=GoalType.DURATION, value=value, subtype=subtype)


def test_daily_duration_goal_counts_todays_records():
    now = DAY + 12 * HOUR_MS
    records = [record(1, 9, 2), record(1, 9, 1, day=ms(2026, 3, 9))]

    progress = compute_progress(daily_goal(3 * HOUR_MS), records, [], now)

    assert progress.current == 2 * HOUR_MS
    assert not progress.reached
    assert progress.left == HOUR_MS
    assert progress.percent == pytest.approx(66.67, abs=0.01)


def test_goal_counts_running_records_too():
    now = DAY + 12 * HOUR_MS
    running = RunningRecord(id=1, time_started=DAY + 11 * HOUR_MS)

    progress = compute_progress(daily_goal(HOUR_MS), [], [running], now)

    assert progress.current >= HOUR_MS
    assert progress.reached


def test_count_goal_counts_records():
    goal = Goal(range=GoalRange.WEEKLY, type=GoalType.COUNT, value=3)
    records = [record(1, 9, 1), record(1, 12, 1), record(1, 15, 1)]

    progress = compute_progress(goal, records, [], DAY + 20 * HOUR_MS)

    assert progress.current == 3
    assert progress.reached


def test_limit_goal_reports_when_exceeded():
    goal = daily_goal(HOUR_MS, subtype=GoalSubtype.LIMIT)
    progress = compute_progress(goal, [record(1, 9, 2)], [], DAY + 12 * HOUR_MS)
    assert progress.exceeded_limit


def test_session_goal_uses_the_running_record_only():
    goal = Goal(range=GoalRange.SESSION, type=GoalType.DURATION, value=HOUR_MS)
    now = DAY + 12 * HOUR_MS
    running = RunningRecord(id=1, time_started=now - 30 * MINUTE_MS)

    progress = compute_progress(goal, [record(1, 5, 5)], [running], now)

    assert progress.current == pytest.approx(30 * MINUTE_MS, abs=2_000)


def test_daily_goal_is_inactive_on_excluded_days():
    goal = daily_goal(HOUR_MS)
    goal.days_of_week = {5, 6}  # weekend only
    assert not is_active_today(goal, DAY)  # DAY is a Tuesday

    goal.days_of_week = {1}
    assert is_active_today(goal, DAY)


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="requires POSIX timezone support")
def test_daily_goal_weekday_shift_is_dst_safe(monkeypatch):
    previous_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Europe/Berlin")
    time.tzset()
    try:
        goal = daily_goal(HOUR_MS)
        goal.days_of_week = {6}  # Sunday
        now = ms(2025, 3, 30, 4, 30)  # DST spring-forward day

        assert is_active_today(goal, now, 4 * HOUR_MS)
    finally:
        if previous_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", previous_tz)
        time.tzset()
