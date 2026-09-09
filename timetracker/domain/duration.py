"""Duration handling — the counterpart of the app's ``DurationMapper``."""

from __future__ import annotations

import re

SECOND_MS = 1_000
MINUTE_MS = 60 * SECOND_MS
HOUR_MS = 60 * MINUTE_MS
DAY_MS = 24 * HOUR_MS


def map_duration(time_started: int, time_ended: int, show_seconds: bool = True) -> int:
    """Duration of a range in ms; drops the seconds part when they are hidden."""
    duration = max(time_ended - time_started, 0)
    if not show_seconds:
        duration = duration // MINUTE_MS * MINUTE_MS
    return duration


def format_duration(duration_ms: int, show_seconds: bool = True) -> str:
    """``1h 30m 15s`` / ``30m`` / ``15s`` — the app's compact duration format."""
    duration_ms = max(duration_ms, 0)
    hours, rest = divmod(duration_ms, HOUR_MS)
    minutes, rest = divmod(rest, MINUTE_MS)
    seconds = rest // SECOND_MS

    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    if show_seconds and (seconds or not parts):
        parts.append(f"{seconds}s")
    if not parts:
        parts.append("0m")
    return " ".join(parts)


def format_timer(duration_ms: int) -> str:
    """``H:MM:SS`` — used for the ticking timer on a running activity."""
    duration_ms = max(duration_ms, 0)
    hours, rest = divmod(duration_ms, HOUR_MS)
    minutes, rest = divmod(rest, MINUTE_MS)
    seconds = rest // SECOND_MS
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def format_hours(duration_ms: int) -> float:
    return round(duration_ms / HOUR_MS, 2)


def parse_duration(text: str) -> int | None:
    """Parse ``1h 30m``, ``90m``, ``1:30`` or ``45`` (minutes) into ms."""
    text = text.strip().lower()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        try:
            values = [int(p) for p in parts]
        except ValueError:
            return None
        while len(values) < 3:
            values.append(0)
        return values[0] * HOUR_MS + values[1] * MINUTE_MS + values[2] * SECOND_MS

    if not _DURATION.match(text):
        return None
    # A number without a unit means minutes.
    return sum(int(number) * _UNIT_MS[unit] for number, unit in _PART.findall(text))


# One or more number groups, each with an optional unit suffix.
_DURATION = re.compile(r"^((\d+|\s)+([hms])?)+$")
_PART = re.compile(r"(\d+)\s*([hms]?)")
_UNIT_MS = {"h": HOUR_MS, "m": MINUTE_MS, "s": SECOND_MS, "": MINUTE_MS}
