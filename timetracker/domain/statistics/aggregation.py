"""Turning grouped records into durations and counts.

Range-first argument order, matching ``filters``. ``show_seconds`` is keyword
only — it changes the number that comes back, so it should be named at the
call site rather than trailing as a bare boolean.
"""

from __future__ import annotations

from ...models import Range, Record, Statistics
from ..duration import map_duration
from .filters import clamp, overlapping
from .grouping import group_by_activity


def total_duration(
    time_range: Range,
    records: list[Record],
    *,
    show_seconds: bool = True,
) -> int:
    """Total tracked time, with records cut down to the range."""
    if time_range.is_undefined:
        return sum(map_duration(r.time_started, r.time_ended, show_seconds) for r in records)
    return sum(
        map_duration(clamped.time_started, clamped.time_ended, show_seconds)
        for clamped in (clamp(time_range, r) for r in overlapping(time_range, records))
    )


def get_statistics(
    time_range: Range,
    grouped_records: dict[int, list[Record]],
    *,
    show_seconds: bool = True,
) -> list[Statistics]:
    """Duration and count per group, sorted by duration like the app's list."""
    result = [
        Statistics(
            id=group_id,
            duration=total_duration(time_range, records, show_seconds=show_seconds),
            count=len(overlapping(time_range, records)),
        )
        for group_id, records in grouped_records.items()
    ]
    return sorted(result, key=lambda s: s.duration, reverse=True)


def get_statistics_from_records(
    time_range: Range,
    records: list[Record],
    *,
    show_seconds: bool = True,
) -> list[Statistics]:
    return get_statistics(time_range, group_by_activity(records), show_seconds=show_seconds)


def sum_durations(statistics: list[Statistics]) -> int:
    """Total across already-computed statistics.

    Named apart from ``total_duration`` on purpose: that one measures records
    against a range, this one adds up rows that were measured already.
    """
    return sum(s.duration for s in statistics)


def percentages(statistics: list[Statistics]) -> dict[int, float]:
    total = sum_durations(statistics)
    if total <= 0:
        return {s.id: 0.0 for s in statistics}
    return {s.id: s.duration / total * 100 for s in statistics}
