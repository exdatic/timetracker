"""Range calculation — the counterpart of ``RangeLength`` and the app's ``TimeMapper``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum

from ..models import Range
from .duration import DAY_MS


class RangeLength(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    ALL = "all"
    LAST = "last"
    CUSTOM = "custom"


def to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def to_datetime(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000)


def _dst_offset(timestamp_ms: int) -> int:
    moment = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).astimezone()
    # Python's system-local tzinfo may be a fixed-offset snapshot, so ``dst()``
    # is not reliable here. Offset differences across one short shift are the
    # DST change that Android exposes through Calendar.DST_OFFSET.
    return int((moment.utcoffset() or timedelta()).total_seconds() * 1000)


def shift_timestamp(timestamp_ms: int, shift: int) -> int:
    """Shift wall-clock time with the Android Calendar DST compensation."""
    if shift == 0:
        return timestamp_ms
    before = _dst_offset(timestamp_ms)
    shifted = timestamp_ms + shift
    after = _dst_offset(shifted)
    correction = before - after
    corrected = shifted + correction
    # Match CalendarExtensions.shift: if correcting crosses the transition a
    # second time (a nonexistent local time), retain the initial result.
    return shifted if after != _dst_offset(corrected) else corrected


def start_of_day(timestamp_ms: int, start_of_day_shift: int = 0) -> int:
    """Start of the day a timestamp falls into, honouring the day-shift setting."""
    shifted = to_datetime(shift_timestamp(timestamp_ms, -start_of_day_shift))
    midnight = datetime(shifted.year, shifted.month, shifted.day)
    return shift_timestamp(to_ms(midnight), start_of_day_shift)


def day_range(day: date, start_of_day_shift: int = 0) -> Range:
    start_of_calendar_day = datetime(day.year, day.month, day.day)
    next_calendar_day = start_of_calendar_day + timedelta(days=1)
    start = shift_timestamp(to_ms(start_of_calendar_day), start_of_day_shift)
    end = shift_timestamp(to_ms(next_calendar_day), start_of_day_shift)
    return Range(start, end)


def _shift_months(moment: datetime, months: int) -> datetime:
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    return datetime(year, month, 1)


def get_range(
    length: RangeLength,
    shift: int = 0,
    first_day_of_week: int = 0,
    start_of_day_shift: int = 0,
    last_days: int = 7,
    custom: Range | None = None,
    now: int | None = None,
) -> Range:
    """Absolute range for a range length.

    ``shift`` moves the window: 0 is the current one, -1 the previous, +1 the next.
    ``first_day_of_week`` is 0 for Monday .. 6 for Sunday.
    """
    from ..models import now_ms

    now = now if now is not None else now_ms()

    if length is RangeLength.ALL:
        return Range(0, 0)

    if length is RangeLength.CUSTOM:
        return custom if custom is not None else Range(0, 0)

    today_start = start_of_day(now, start_of_day_shift)
    logical_today = to_datetime(shift_timestamp(today_start, -start_of_day_shift))

    if length is RangeLength.LAST:
        # Calendar days are not always 24 hours long across DST transitions.
        end_date = logical_today.date() + timedelta(days=1)
        start_date = end_date - timedelta(days=last_days)
        return Range(
            day_range(start_date, start_of_day_shift).time_started,
            day_range(end_date, start_of_day_shift).time_started,
        )

    if length is RangeLength.DAY:
        return day_range(logical_today.date() + timedelta(days=shift), start_of_day_shift)

    if length is RangeLength.WEEK:
        days_since_start = (logical_today.weekday() - first_day_of_week) % 7
        week_start = logical_today.date() - timedelta(days=days_since_start) + timedelta(weeks=shift)
        return Range(
            day_range(week_start, start_of_day_shift).time_started,
            day_range(week_start + timedelta(weeks=1), start_of_day_shift).time_started,
        )

    if length is RangeLength.MONTH:
        month_start = to_ms(_shift_months(logical_today, shift))
        next_month = to_ms(_shift_months(logical_today, shift + 1))
        return Range(
            shift_timestamp(month_start, start_of_day_shift),
            shift_timestamp(next_month, start_of_day_shift),
        )

    if length is RangeLength.YEAR:
        year_start = to_ms(datetime(logical_today.year + shift, 1, 1))
        year_end = to_ms(datetime(logical_today.year + shift + 1, 1, 1))
        return Range(
            shift_timestamp(year_start, start_of_day_shift),
            shift_timestamp(year_end, start_of_day_shift),
        )

    raise ValueError(f"Unsupported range length: {length}")


@dataclass(frozen=True)
class Day:
    """One day-sized bucket, and the calendar date it belongs to.

    Callers kept deriving the date back out of the range with
    ``shift_timestamp`` and ``to_datetime``, each doing the day-shift
    arithmetic again and getting it subtly different. Carry it instead.
    """

    range: Range
    date: date

    @property
    def time_started(self) -> int:
        return self.range.time_started

    @property
    def time_ended(self) -> int:
        return self.range.time_ended


def split_into_days(time_range: Range, start_of_day_shift: int = 0) -> list[Day]:
    """Split a range into day-sized buckets — the x axis of the statistics chart."""
    if time_range.is_undefined or time_range.duration <= 0:
        return []
    result: list[Day] = []
    cursor = start_of_day(time_range.time_started, start_of_day_shift)
    while cursor < time_range.time_ended:
        # The next boundary is simply the start of the day 24 hours on.
        next_day = start_of_day(cursor + DAY_MS, start_of_day_shift)
        bucket = Range(max(cursor, time_range.time_started), min(next_day, time_range.time_ended))
        logical = to_datetime(shift_timestamp(cursor, -start_of_day_shift)).date()
        result.append(Day(range=bucket, date=logical))
        cursor = next_day
    return result


def format_range(
    length: RangeLength,
    time_range: Range,
    start_of_day_shift: int = 0,
) -> str:
    """Human readable title for the selected range, like the app's range header."""
    if length is RangeLength.ALL or time_range.is_undefined:
        return "All records"
    # Convert shifted boundaries back to their logical calendar dates. This is
    # especially important for negative shifts, whose timestamp is on the
    # previous wall-clock date.
    start = to_datetime(shift_timestamp(time_range.time_started, -start_of_day_shift))
    end = to_datetime(shift_timestamp(time_range.time_ended - 1, -start_of_day_shift))
    if length is RangeLength.DAY:
        return start.strftime("%a, %d %b %Y")
    if length is RangeLength.MONTH:
        return start.strftime("%B %Y")
    if length is RangeLength.YEAR:
        return start.strftime("%Y")
    return f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"
