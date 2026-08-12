"""Domain models, ported from the Android app's ``domain`` module.

Timestamps are milliseconds since the epoch, as in the original app.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from .colors import AppColor

UNTRACKED_ITEM_ID = -1
UNCATEGORIZED_ITEM_ID = -2


def now_ms() -> int:
    """Current time in milliseconds, with the millisecond part dropped."""
    return (int(time.time() * 1000) // 1000) * 1000


@dataclass(frozen=True)
class Range:
    time_started: int
    time_ended: int

    @property
    def duration(self) -> int:
        return self.time_ended - self.time_started

    @property
    def is_undefined(self) -> bool:
        return self.time_started == 0 and self.time_ended == 0

    def is_overlapping_with(self, other: "Range") -> bool:
        return self.time_started < other.time_ended and self.time_ended > other.time_started


@dataclass
class RecordType:
    """An activity that can be tracked."""

    id: int = 0
    name: str = ""
    icon: str = "⭐"
    color: AppColor = field(default_factory=AppColor)
    default_duration: int = 0  # ms, 0 = no default
    note: str = ""
    hidden: bool = False


@dataclass
class Category:
    id: int = 0
    name: str = ""
    color: AppColor = field(default_factory=AppColor)
    note: str = ""


class TagValueType(str, Enum):
    NONE = "none"
    TEXT = "text"
    NUMBER = "number"


@dataclass
class RecordTag:
    """A tag. ``icon_color_source`` != 0 means: take the color from that activity."""

    id: int = 0
    name: str = ""
    icon: str = "⭐"
    color: AppColor = field(default_factory=AppColor)
    icon_color_source: int = 0
    note: str = ""
    archived: bool = False
    value_type: TagValueType = TagValueType.NONE
    value_suffix: str = ""


@dataclass
class Record:
    """A finished record."""

    id: int = 0
    type_id: int = 0
    time_started: int = 0
    time_ended: int = 0
    comment: str = ""
    tag_ids: list[int] = field(default_factory=list)

    @property
    def duration(self) -> int:
        return self.time_ended - self.time_started

    @property
    def range(self) -> Range:
        return Range(self.time_started, self.time_ended)


@dataclass
class RunningRecord:
    """A record in progress. Its ``id`` is the activity id, as in the app."""

    id: int = 0
    time_started: int = 0
    comment: str = ""
    tag_ids: list[int] = field(default_factory=list)

    @property
    def type_id(self) -> int:
        return self.id

    @property
    def time_ended(self) -> int:
        return now_ms()

    @property
    def duration(self) -> int:
        return self.time_ended - self.time_started

    @property
    def range(self) -> Range:
        return Range(self.time_started, self.time_ended)

    def to_record(self) -> Record:
        return Record(
            type_id=self.id,
            time_started=self.time_started,
            time_ended=self.time_ended,
            comment=self.comment,
            tag_ids=list(self.tag_ids),
        )


class GoalIdType(str, Enum):
    TYPE = "type"
    CATEGORY = "category"
    TAG = "tag"


class GoalRange(str, Enum):
    SESSION = "session"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class GoalType(str, Enum):
    DURATION = "duration"
    COUNT = "count"


class GoalSubtype(str, Enum):
    GOAL = "goal"
    LIMIT = "limit"


@dataclass
class Goal:
    id: int = 0
    id_type: GoalIdType = GoalIdType.TYPE
    id_value: int = 0
    range: GoalRange = GoalRange.DAILY
    type: GoalType = GoalType.DURATION
    value: int = 0  # ms for DURATION, a count for COUNT
    subtype: GoalSubtype = GoalSubtype.GOAL
    days_of_week: set[int] = field(default_factory=lambda: set(range(7)))  # 0 = Monday


@dataclass
class Statistics:
    """Aggregated time for one activity/category/tag."""

    id: int
    duration: int
    count: int
