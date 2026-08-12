"""Demo data, so a fresh install has something to look at."""

from __future__ import annotations

import random
from datetime import timedelta

from . import repository as repo
from .colors import AppColor
from .domain.duration import HOUR_MS, MINUTE_MS
from .domain.ranges import start_of_day, to_datetime, to_ms
from .models import (
    Category,
    Goal,
    GoalIdType,
    GoalRange,
    GoalSubtype,
    GoalType,
    Record,
    RecordTag,
    RecordType,
    now_ms,
)

# name, icon, color index, category, typical start hour, typical hours, days per week
DEMO_ACTIVITIES: list[tuple[str, str, int, str, float, float, float]] = [
    ("Work", "💼", 4, "Productive", 9.0, 4.5, 5),
    ("Meetings", "👥", 5, "Productive", 14.0, 1.2, 4),
    ("Learning", "📚", 8, "Productive", 20.0, 1.0, 3),
    ("Sport", "🏃", 9, "Health", 18.0, 1.0, 3),
    ("Sleep", "😴", 3, "Health", 23.0, 7.5, 7),
    ("Cooking", "🍳", 14, "Chores", 18.5, 0.7, 5),
    ("Housework", "🧹", 16, "Chores", 11.0, 0.8, 2),
    ("Gaming", "🎮", 2, "Leisure", 21.0, 1.5, 3),
    ("Reading", "📖", 7, "Leisure", 22.0, 0.8, 4),
    ("Social", "🍻", 1, "Leisure", 19.0, 2.0, 2),
]

DEMO_CATEGORIES: list[tuple[str, int]] = [
    ("Productive", 4),
    ("Health", 9),
    ("Chores", 16),
    ("Leisure", 2),
]

DEMO_TAGS: list[tuple[str, str, int]] = [
    ("Focused", "🎯", 9),
    ("Interrupted", "🔔", 0),
    ("Remote", "🏠", 6),
    ("Office", "🏢", 18),
]


def seed_demo_data(days: int = 30, seed: int = 7) -> None:
    """Populate an empty database with activities, tags, goals and history."""
    rng = random.Random(seed)

    category_ids = {
        name: repo.save_category(Category(name=name, color=AppColor(color_id=color)))
        for name, color in DEMO_CATEGORIES
    }

    tag_ids = [
        repo.save_tag(RecordTag(name=name, icon=icon, color=AppColor(color_id=color)))
        for name, icon, color in DEMO_TAGS
    ]

    type_ids: dict[str, int] = {}
    for name, icon, color, category, _, _, _ in DEMO_ACTIVITIES:
        type_id = repo.save_record_type(
            RecordType(name=name, icon=icon, color=AppColor(color_id=color))
        )
        type_ids[name] = type_id
        repo.set_categories_of_type(type_id, [category_ids[category]])

    _seed_records(rng, type_ids, tag_ids, days)
    _seed_goals(type_ids, category_ids)


def _seed_records(
    rng: random.Random,
    type_ids: dict[str, int],
    tag_ids: list[int],
    days: int,
) -> None:
    today_start = start_of_day(now_ms())

    for day_offset in range(days, 0, -1):
        day = to_datetime(today_start) - timedelta(days=day_offset - 1)
        is_weekend = day.weekday() >= 5

        for name, _, _, _, start_hour, typical_hours, per_week in DEMO_ACTIVITIES:
            if rng.random() > per_week / 7:
                continue
            if is_weekend and name in ("Work", "Meetings"):
                continue

            hours = max(typical_hours * rng.uniform(0.6, 1.4), 0.2)
            start = to_ms(day) + int((start_hour + rng.uniform(-1, 1)) * HOUR_MS)
            end = start + int(hours * HOUR_MS)
            if end > now_ms():
                continue

            tags = rng.sample(tag_ids, k=rng.choice([0, 1, 1, 2]))
            repo.save_record(
                Record(
                    type_id=type_ids[name],
                    time_started=start,
                    time_ended=end,
                    comment=rng.choice(["", "", "", "Went well", "Rushed"]),
                    tag_ids=tags,
                )
            )


def _seed_goals(type_ids: dict[str, int], category_ids: dict[str, int]) -> None:
    goals = [
        Goal(
            id_type=GoalIdType.TYPE,
            id_value=type_ids["Work"],
            range=GoalRange.DAILY,
            type=GoalType.DURATION,
            value=6 * HOUR_MS,
            subtype=GoalSubtype.GOAL,
            days_of_week={0, 1, 2, 3, 4},
        ),
        Goal(
            id_type=GoalIdType.TYPE,
            id_value=type_ids["Sport"],
            range=GoalRange.WEEKLY,
            type=GoalType.COUNT,
            value=3,
            subtype=GoalSubtype.GOAL,
        ),
        Goal(
            id_type=GoalIdType.TYPE,
            id_value=type_ids["Gaming"],
            range=GoalRange.DAILY,
            type=GoalType.DURATION,
            value=90 * MINUTE_MS,
            subtype=GoalSubtype.LIMIT,
        ),
        Goal(
            id_type=GoalIdType.CATEGORY,
            id_value=category_ids["Productive"],
            range=GoalRange.WEEKLY,
            type=GoalType.DURATION,
            value=30 * HOUR_MS,
            subtype=GoalSubtype.GOAL,
        ),
    ]
    for goal in goals:
        repo.save_goal(goal)


def database_is_empty() -> bool:
    return not any(
        (
            repo.get_record_types(),
            repo.get_categories(),
            repo.get_tags(include_archived=True),
            repo.get_records(),
            repo.get_running_records(),
            repo.get_goals(),
        )
    )
