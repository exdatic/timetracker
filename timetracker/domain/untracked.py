"""Untracked time — ports ``UnCoveredRangesMapper`` and ``UntrackedRecordMapper``."""

from __future__ import annotations

from ..models import UNTRACKED_ITEM_ID, Range, Record


def uncovered_ranges(start: int, end: int, ranges: list[Range]) -> list[Range]:
    """The parts of ``[start, end)`` that no range in ``ranges`` covers."""
    if end <= start:
        return []

    normalized = [
        Range(min(r.time_started, r.time_ended), max(r.time_started, r.time_ended))
        for r in ranges
    ]
    covered = sorted(
        (r for r in normalized if r.time_ended >= start and r.time_started <= end),
        key=lambda r: r.time_started,
    )

    result: list[Range] = []
    cursor = start
    for current in covered:
        if current.time_started > cursor:
            result.append(Range(cursor, min(current.time_started, end)))
        cursor = max(cursor, current.time_ended)
        if cursor >= end:
            break
    if cursor < end:
        result.append(Range(cursor, end))
    return [r for r in result if r.duration > 0]


def passes_cutoff(duration: int, duration_cutoff_seconds: int) -> bool:
    """Short gaps can be ignored — the app's ``ignore short untracked`` setting."""
    if duration_cutoff_seconds > 0:
        return duration > duration_cutoff_seconds * 1000
    return True


def calculate_untracked_ranges(
    records: list[Range],
    time_range: Range,
    min_start: int,
    max_end: int,
    duration_cutoff_seconds: int = 0,
) -> list[Range]:
    untracked_start = max(min_start, time_range.time_started)
    if time_range.time_ended < untracked_start:
        return []
    untracked_end = min(max_end, time_range.time_ended)
    if time_range.time_started > untracked_end:
        return []

    clamped = [
        Range(max(r.time_started, untracked_start), min(r.time_ended, untracked_end))
        for r in records
    ]
    return [
        r
        for r in uncovered_ranges(untracked_start, untracked_end, clamped)
        if passes_cutoff(r.duration, duration_cutoff_seconds)
    ]


def get_untracked_records(
    time_range: Range,
    records: list[Range],
    first_record_start: int | None,
    now: int,
    duration_cutoff_seconds: int = 0,
) -> list[Record]:
    """Untracked gaps as pseudo-records, exactly as the app renders them.

    Untracked time is only counted from the first record onwards and never
    reaches into the future.
    """
    if first_record_start is None:
        return []

    actual_range = (
        Range(first_record_start, now) if time_range.is_undefined else time_range
    )
    return [
        Record(
            type_id=UNTRACKED_ITEM_ID,
            time_started=r.time_started,
            time_ended=r.time_ended,
        )
        for r in calculate_untracked_ranges(
            records=records,
            time_range=actual_range,
            min_start=first_record_start,
            max_end=now,
            duration_cutoff_seconds=duration_cutoff_seconds,
        )
    ]
