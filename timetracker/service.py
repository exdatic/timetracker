"""Wiring between the pure domain logic and the database."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from . import repository as repo
from .db import db_path
from .domain.goals import GoalProgress, compute_progress
from .domain.ranges import RangeLength, get_range
from .domain.statistics import (
    ChartFilterType,
    group_by_activity,
    group_by_category,
    group_by_tag,
)
from .domain.statistics import get_statistics as _get_statistics
from .domain.untracked import get_untracked_records
from .models import (
    UNCATEGORIZED_ITEM_ID,
    Goal,
    GoalIdType,
    Range,
    Record,
    RunningRecord,
    Statistics,
    now_ms,
)


@dataclass
class Settings:
    show_untracked: bool = False
    show_seconds: bool = True
    first_day_of_week: int = 0
    start_of_day_shift: int = 0
    ignore_short_untracked: int = 0
    allow_multitasking: bool = True


def load_settings() -> Settings:
    prefs = repo.get_prefs()
    return Settings(
        show_untracked=prefs["show_untracked"] == "true",
        show_seconds=prefs["show_seconds"] == "true",
        first_day_of_week=int(prefs["first_day_of_week"]),
        start_of_day_shift=int(prefs["start_of_day_shift"]),
        ignore_short_untracked=int(prefs["ignore_short_untracked"]),
        allow_multitasking=prefs["allow_multitasking"] == "true",
    )


def current_range(
    length: RangeLength,
    shift: int = 0,
    last_days: int = 7,
    custom: Range | None = None,
    settings: Settings | None = None,
) -> Range:
    settings = settings or load_settings()
    return get_range(
        length,
        shift=shift,
        first_day_of_week=settings.first_day_of_week,
        start_of_day_shift=settings.start_of_day_shift,
        last_days=last_days,
        custom=custom,
    )


def records_for_range(time_range: Range, include_running: bool = True) -> list[Record]:
    """Finished records in the range, plus running records as they stand now."""
    records = repo.get_records(time_range)
    if not include_running:
        return records
    running = [r.to_record() for r in repo.get_running_records()]
    if not time_range.is_undefined:
        running = [
            r
            for r in running
            if r.time_started < time_range.time_ended and r.time_ended > time_range.time_started
        ]
    return records + running


def untracked_for_range(time_range: Range, records: list[Record]) -> list[Record]:
    settings = load_settings()
    return get_untracked_records(
        time_range=time_range,
        records=[r.range for r in records],
        first_record_start=repo.get_first_record_start(),
        now=now_ms(),
        duration_cutoff_seconds=settings.ignore_short_untracked,
    )


def statistics_for_range(
    time_range: Range,
    filter_type: ChartFilterType = ChartFilterType.ACTIVITY,
    add_untracked: bool | None = None,
) -> tuple[list[Statistics], list[Record]]:
    """Statistics for a range plus the records they were computed from."""
    settings = load_settings()
    add_untracked = settings.show_untracked if add_untracked is None else add_untracked

    records = records_for_range(time_range)
    if add_untracked:
        records = records + untracked_for_range(time_range, records)

    if filter_type is ChartFilterType.CATEGORY:
        links: dict[int, list[int]] = {}
        for type_id, category_id in repo.get_type_category_links():
            links.setdefault(type_id, []).append(category_id)
        grouped = group_by_category(records, links, uncategorized_id=UNCATEGORIZED_ITEM_ID)
    elif filter_type is ChartFilterType.TAG:
        grouped = group_by_tag(records, untagged_id=UNCATEGORIZED_ITEM_ID)
    else:
        grouped = group_by_activity(records)

    return _get_statistics(time_range, grouped, settings.show_seconds), records


def goal_target_type_ids(goal: Goal) -> list[int] | None:
    """Activities a goal covers; None when the goal is filtered by tag instead."""
    if goal.id_type is GoalIdType.TYPE:
        return [goal.id_value]
    if goal.id_type is GoalIdType.CATEGORY:
        return repo.get_types_of_category(goal.id_value)
    return None


@lru_cache(maxsize=None)
def _records_snapshot(path: str, type_ids: tuple[int, ...] | None, tick: int) -> list[Record]:
    """Goal progress rescans the whole history on every render; one snapshot
    per database and second is plenty."""
    return repo.get_records(type_ids=list(type_ids) if type_ids is not None else None)


def records_for_goal(goal: Goal) -> tuple[list[Record], list[RunningRecord]]:
    type_ids = goal_target_type_ids(goal)
    running = repo.get_running_records()
    tick = now_ms() // 1000
    if type_ids is not None:
        records = _records_snapshot(str(db_path()), tuple(type_ids), tick)
        running = [r for r in running if r.id in type_ids]
    else:
        records = [r for r in _records_snapshot(str(db_path()), None, tick) if goal.id_value in r.tag_ids]
        running = [r for r in running if goal.id_value in r.tag_ids]
    return records, running


def progress_for_goal(goal: Goal) -> GoalProgress:
    records, running = records_for_goal(goal)
    settings = load_settings()
    return compute_progress(
        goal=goal,
        records=records,
        running_records=running,
        now=now_ms(),
        first_day_of_week=settings.first_day_of_week,
        start_of_day_shift=settings.start_of_day_shift,
        show_seconds=settings.show_seconds,
    )


def progress_for_all_goals() -> list[GoalProgress]:
    return [progress_for_goal(goal) for goal in repo.get_goals()]


def goals_of_type(type_id: int) -> list[Goal]:
    """Goals shown on an activity card: its own, and those of its categories."""
    category_ids = set(repo.get_categories_of_type(type_id))
    result = []
    for goal in repo.get_goals():
        if goal.id_type is GoalIdType.TYPE and goal.id_value == type_id:
            result.append(goal)
        elif goal.id_type is GoalIdType.CATEGORY and goal.id_value in category_ids:
            result.append(goal)
    return result


def start_activity(type_id: int, comment: str = "", tag_ids: list[int] | None = None) -> None:
    """Start tracking; without multitasking any other running activity stops."""
    settings = load_settings()
    if not settings.allow_multitasking:
        for running in repo.get_running_records():
            if running.id != type_id:
                repo.stop_running_record(running.id)
    repo.start_running_record(type_id, comment=comment, tag_ids=tag_ids or [])
