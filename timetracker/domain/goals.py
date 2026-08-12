"""Goal progress — a port of the app's goal interactors.

A goal targets an activity, a category or a tag; it counts either time or
number of records within a session, day, week or month; and it is either a
goal to reach or a limit not to exceed.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import (
    Goal,
    GoalRange,
    GoalSubtype,
    GoalType,
    Range,
    Record,
    RunningRecord,
)

from .duration import format_duration
from .ranges import RangeLength, get_range, shift_timestamp, to_datetime
from .statistics import duration_in_range, records_in_range


@dataclass
class GoalProgress:
    goal: Goal
    current: int  # ms for a duration goal, a count for a count goal
    target: int
    active_today: bool

    @property
    def percent(self) -> float:
        if self.target <= 0:
            return 0.0
        return min(self.current / self.target * 100, 100.0)

    @property
    def reached(self) -> bool:
        return self.current >= self.target

    @property
    def exceeded_limit(self) -> bool:
        return self.goal.subtype is GoalSubtype.LIMIT and self.current > self.target

    @property
    def left(self) -> int:
        return max(self.target - self.current, 0)

    def format_value(self, value: int, show_seconds: bool = True) -> str:
        if self.goal.type is GoalType.DURATION:
            return format_duration(value, show_seconds)
        return str(value)

    def describe(self, show_seconds: bool = True) -> str:
        current = self.format_value(self.current, show_seconds)
        target = self.format_value(self.target, show_seconds)
        return f"{current} / {target}"


GOAL_RANGE_LENGTHS: dict[GoalRange, RangeLength] = {
    GoalRange.DAILY: RangeLength.DAY,
    GoalRange.WEEKLY: RangeLength.WEEK,
    GoalRange.MONTHLY: RangeLength.MONTH,
}


def goal_range(
    goal: Goal,
    now: int,
    first_day_of_week: int = 0,
    start_of_day_shift: int = 0,
) -> Range | None:
    """Range a non-session goal is measured over; None for session goals."""
    length = GOAL_RANGE_LENGTHS.get(goal.range)
    if length is None:
        return None
    return get_range(
        length,
        first_day_of_week=first_day_of_week,
        start_of_day_shift=start_of_day_shift,
        now=now,
    )


def is_active_today(goal: Goal, now: int, start_of_day_shift: int = 0) -> bool:
    """Daily goals can be restricted to certain weekdays."""
    if goal.range is not GoalRange.DAILY:
        return True
    today = to_datetime(shift_timestamp(now, -start_of_day_shift)).weekday()  # 0 = Monday
    return today in goal.days_of_week


def compute_progress(
    goal: Goal,
    records: list[Record],
    running_records: list[RunningRecord],
    now: int,
    first_day_of_week: int = 0,
    start_of_day_shift: int = 0,
    show_seconds: bool = True,
) -> GoalProgress:
    """Progress of a goal against the records that already belong to it.

    ``records`` and ``running_records`` must already be filtered down to what
    the goal targets (activity, category or tag).
    """
    active = is_active_today(goal, now, start_of_day_shift)

    if goal.range is GoalRange.SESSION:
        durations = [max(now - r.time_started, 0) for r in running_records]
        if goal.type is GoalType.DURATION:
            current = max(durations, default=0)
        else:
            current = len(running_records)
        return GoalProgress(goal=goal, current=current, target=goal.value, active_today=active)

    time_range = goal_range(goal, now, first_day_of_week, start_of_day_shift)
    assert time_range is not None
    # Running records count up to `now`, not to whatever the clock says later.
    all_records = records + [
        Record(
            type_id=r.id,
            time_started=r.time_started,
            time_ended=max(now, r.time_started),
            comment=r.comment,
            tag_ids=list(r.tag_ids),
        )
        for r in running_records
    ]

    if goal.type is GoalType.DURATION:
        current = duration_in_range(all_records, time_range, show_seconds)
    else:
        current = len(records_in_range(all_records, time_range))

    return GoalProgress(goal=goal, current=current, target=goal.value, active_today=active)
