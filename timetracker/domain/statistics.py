"""Statistics aggregation — a port of the app's ``StatisticsInteractor``.

Everything here is pure: it takes records and gives back numbers, so the
calculations can be tested without a database.
"""

from __future__ import annotations

from enum import Enum

from ..models import UNTRACKED_ITEM_ID, Range, Record, Statistics

from .duration import map_duration


class ChartFilterType(str, Enum):
    ACTIVITY = "activity"
    CATEGORY = "category"
    TAG = "tag"


def records_in_range(records: list[Record], time_range: Range) -> list[Record]:
    """Records overlapping the range (the app's ``getRecordsFromRange``)."""
    if time_range.is_undefined:
        return list(records)
    return [
        r
        for r in records
        if r.time_started < time_range.time_ended and r.time_ended > time_range.time_started
    ]


def clamp_to_range(record: Record, time_range: Range) -> Range:
    return Range(
        max(record.time_started, time_range.time_started),
        min(record.time_ended, time_range.time_ended),
    )


def duration_in_range(records: list[Record], time_range: Range, show_seconds: bool = True) -> int:
    """Total tracked time, with records cut down to the range."""
    if time_range.is_undefined:
        return sum(map_duration(r.time_started, r.time_ended, show_seconds) for r in records)
    return sum(
        map_duration(clamped.time_started, clamped.time_ended, show_seconds)
        for clamped in (clamp_to_range(r, time_range) for r in records_in_range(records, time_range))
    )


def group_by_activity(records: list[Record]) -> dict[int, list[Record]]:
    grouped: dict[int, list[Record]] = {}
    for record in records:
        grouped.setdefault(record.type_id, []).append(record)
    return grouped


def group_by_category(
    records: list[Record],
    categories_of_type: dict[int, list[int]],
    uncategorized_id: int | None = None,
) -> dict[int, list[Record]]:
    grouped: dict[int, list[Record]] = {}
    for record in records:
        if record.type_id == UNTRACKED_ITEM_ID:
            grouped.setdefault(UNTRACKED_ITEM_ID, []).append(record)
            continue
        category_ids = categories_of_type.get(record.type_id, [])
        if not category_ids:
            if uncategorized_id is None:
                continue
            category_ids = [uncategorized_id]
        for category_id in category_ids:
            grouped.setdefault(category_id, []).append(record)
    return grouped


def group_by_tag(records: list[Record], untagged_id: int | None = None) -> dict[int, list[Record]]:
    grouped: dict[int, list[Record]] = {}
    for record in records:
        if record.type_id == UNTRACKED_ITEM_ID:
            grouped.setdefault(UNTRACKED_ITEM_ID, []).append(record)
            continue
        tag_ids = record.tag_ids
        if not tag_ids:
            if untagged_id is None:
                continue
            tag_ids = [untagged_id]
        for tag_id in tag_ids:
            grouped.setdefault(tag_id, []).append(record)
    return grouped


def get_statistics(
    time_range: Range,
    grouped_records: dict[int, list[Record]],
    show_seconds: bool = True,
) -> list[Statistics]:
    """Duration and count per group, sorted by duration like the app's list."""
    result = [
        Statistics(
            id=group_id,
            duration=duration_in_range(records, time_range, show_seconds),
            count=len(records_in_range(records, time_range)),
        )
        for group_id, records in grouped_records.items()
    ]
    return sorted(result, key=lambda s: s.duration, reverse=True)


def get_statistics_from_records(
    time_range: Range,
    records: list[Record],
    show_seconds: bool = True,
) -> list[Statistics]:
    return get_statistics(time_range, group_by_activity(records), show_seconds)


def total_duration(statistics: list[Statistics]) -> int:
    return sum(s.duration for s in statistics)


def percentages(statistics: list[Statistics]) -> dict[int, float]:
    total = total_duration(statistics)
    if total <= 0:
        return {s.id: 0.0 for s in statistics}
    return {s.id: s.duration / total * 100 for s in statistics}
