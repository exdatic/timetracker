"""Selecting and trimming records against a range.

Range-first argument order throughout: the range is the thing being asked
about, the records are what it is asked of.
"""

from __future__ import annotations

from enum import Enum

from ...models import Range, Record


class ChartFilterType(str, Enum):
    ACTIVITY = "activity"
    CATEGORY = "category"
    TAG = "tag"


def overlapping(time_range: Range, records: list[Record]) -> list[Record]:
    """Records overlapping the range (the app's ``getRecordsFromRange``).

    Overlap, not containment: a record that starts before the range and ends
    inside it counts.
    """
    if time_range.is_undefined:
        return list(records)
    return [
        r
        for r in records
        if r.time_started < time_range.time_ended and r.time_ended > time_range.time_started
    ]


def clamp(time_range: Range, record: Record) -> Range:
    """The part of a record that falls inside the range."""
    return Range(
        max(record.time_started, time_range.time_started),
        min(record.time_ended, time_range.time_ended),
    )
