"""Data access layer — the Python counterpart of the app's DAOs and interactors."""

from __future__ import annotations

import sqlite3

from .colors import AppColor
from .db import connect
from .models import (
    Category,
    Goal,
    GoalIdType,
    GoalRange,
    GoalSubtype,
    GoalType,
    Range,
    Record,
    RecordTag,
    RecordType,
    RunningRecord,
    TagValueType,
    now_ms,
)

# --------------------------------------------------------------------------- #
# Row mapping
# --------------------------------------------------------------------------- #


def _color(row: sqlite3.Row) -> AppColor:
    return AppColor(color_id=row["color_id"], color_int=row["color_int"])


def _to_record_type(row: sqlite3.Row) -> RecordType:
    return RecordType(
        id=row["id"],
        name=row["name"],
        icon=row["icon"],
        color=_color(row),
        default_duration=row["default_duration"],
        note=row["note"],
        hidden=bool(row["hidden"]),
    )


def _to_category(row: sqlite3.Row) -> Category:
    return Category(id=row["id"], name=row["name"], color=_color(row), note=row["note"])


def _to_tag(row: sqlite3.Row) -> RecordTag:
    return RecordTag(
        id=row["id"],
        name=row["name"],
        icon=row["icon"],
        color=_color(row),
        icon_color_source=row["icon_color_source"],
        note=row["note"],
        archived=bool(row["archived"]),
        value_type=TagValueType(row["value_type"]),
        value_suffix=row["value_suffix"],
    )


def _to_goal(row: sqlite3.Row) -> Goal:
    days = {int(d) for d in row["days_of_week"].split(",") if d != ""}
    return Goal(
        id=row["id"],
        id_type=GoalIdType(row["id_type"]),
        id_value=row["id_value"],
        range=GoalRange(row["range"]),
        type=GoalType(row["type"]),
        value=row["value"],
        subtype=GoalSubtype(row["subtype"]),
        days_of_week=days,
    )


# --------------------------------------------------------------------------- #
# Activities (RecordType)
# --------------------------------------------------------------------------- #


def get_record_types(include_hidden: bool = True) -> list[RecordType]:
    query = "SELECT * FROM recordTypes"
    if not include_hidden:
        query += " WHERE hidden = 0"
    query += " ORDER BY name COLLATE NOCASE"
    with connect() as conn:
        return [_to_record_type(row) for row in conn.execute(query)]


def get_record_type(type_id: int) -> RecordType | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM recordTypes WHERE id = ?", (type_id,)).fetchone()
    return _to_record_type(row) if row else None


def record_types_by_id(include_hidden: bool = True) -> dict[int, RecordType]:
    return {t.id: t for t in get_record_types(include_hidden)}


def _upsert(
    conn: sqlite3.Connection,
    table: str,
    entity_id: int,
    columns: dict[str, object],
) -> int:
    """Insert a new row, or update the row with this id.

    Restoring a backup writes rows with their original ids, so an id that is
    set does not necessarily mean the row already exists.
    """
    names = [f'"{name}"' for name in columns]  # some column names are SQL keywords
    values = list(columns.values())
    if entity_id:
        assignments = ", ".join(f"{name} = excluded.{name}" for name in names)
        conn.execute(
            f"INSERT INTO {table} (id, {', '.join(names)}) "
            f"VALUES ({', '.join('?' * (len(names) + 1))}) "
            f"ON CONFLICT(id) DO UPDATE SET {assignments}",
            [entity_id, *values],
        )
        return entity_id
    cursor = conn.execute(
        f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
        values,
    )
    return int(cursor.lastrowid or 0)


def save_record_type(record_type: RecordType) -> int:
    with connect() as conn:
        return _upsert(
            conn,
            "recordTypes",
            record_type.id,
            {
                "name": record_type.name,
                "icon": record_type.icon,
                "color_id": record_type.color.color_id,
                "color_int": record_type.color.color_int,
                "default_duration": record_type.default_duration,
                "note": record_type.note,
                "hidden": int(record_type.hidden),
            },
        )


def delete_record_type(type_id: int) -> None:
    """Remove the activity together with its records, links and goals."""
    with connect() as conn:
        conn.execute(
            "DELETE FROM recordToRecordTag WHERE record_id IN "
            "(SELECT id FROM records WHERE type_id = ?)",
            (type_id,),
        )
        conn.execute("DELETE FROM records WHERE type_id = ?", (type_id,))
        conn.execute("DELETE FROM runningRecords WHERE id = ?", (type_id,))
        conn.execute("DELETE FROM runningRecordToRecordTag WHERE running_record_id = ?", (type_id,))
        conn.execute("DELETE FROM recordTypeCategories WHERE record_type_id = ?", (type_id,))
        conn.execute("DELETE FROM recordTypeToTag WHERE record_type_id = ?", (type_id,))
        conn.execute(
            "DELETE FROM goals WHERE id_type = 'type' AND id_value = ?",
            (type_id,),
        )
        conn.execute("DELETE FROM recordTypes WHERE id = ?", (type_id,))


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #


def get_categories() -> list[Category]:
    with connect() as conn:
        return [
            _to_category(row)
            for row in conn.execute("SELECT * FROM categories ORDER BY name COLLATE NOCASE")
        ]


def save_category(category: Category) -> int:
    with connect() as conn:
        return _upsert(
            conn,
            "categories",
            category.id,
            {
                "name": category.name,
                "color_id": category.color.color_id,
                "color_int": category.color.color_int,
                "note": category.note,
            },
        )


def delete_category(category_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM recordTypeCategories WHERE category_id = ?", (category_id,))
        conn.execute(
            "DELETE FROM goals WHERE id_type = 'category' AND id_value = ?",
            (category_id,),
        )
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))


def get_type_category_links() -> list[tuple[int, int]]:
    with connect() as conn:
        return [
            (row["record_type_id"], row["category_id"])
            for row in conn.execute("SELECT * FROM recordTypeCategories")
        ]


def get_categories_of_type(type_id: int) -> list[int]:
    with connect() as conn:
        return [
            row["category_id"]
            for row in conn.execute(
                "SELECT category_id FROM recordTypeCategories WHERE record_type_id = ?",
                (type_id,),
            )
        ]


def get_types_of_category(category_id: int) -> list[int]:
    with connect() as conn:
        return [
            row["record_type_id"]
            for row in conn.execute(
                "SELECT record_type_id FROM recordTypeCategories WHERE category_id = ?",
                (category_id,),
            )
        ]


def set_categories_of_type(type_id: int, category_ids: list[int]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM recordTypeCategories WHERE record_type_id = ?", (type_id,))
        conn.executemany(
            "INSERT INTO recordTypeCategories (record_type_id, category_id) VALUES (?, ?)",
            [(type_id, category_id) for category_id in category_ids],
        )


# --------------------------------------------------------------------------- #
# Tags
# --------------------------------------------------------------------------- #


def get_tags(include_archived: bool = False) -> list[RecordTag]:
    query = "SELECT * FROM recordTags"
    if not include_archived:
        query += " WHERE archived = 0"
    query += " ORDER BY name COLLATE NOCASE"
    with connect() as conn:
        return [_to_tag(row) for row in conn.execute(query)]


def tags_by_id(include_archived: bool = True) -> dict[int, RecordTag]:
    return {tag.id: tag for tag in get_tags(include_archived)}


def save_tag(tag: RecordTag) -> int:
    with connect() as conn:
        return _upsert(
            conn,
            "recordTags",
            tag.id,
            {
                "name": tag.name,
                "icon": tag.icon,
                "color_id": tag.color.color_id,
                "color_int": tag.color.color_int,
                "icon_color_source": tag.icon_color_source,
                "note": tag.note,
                "archived": int(tag.archived),
                "value_type": tag.value_type.value,
                "value_suffix": tag.value_suffix,
            },
        )


def delete_tag(tag_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM recordToRecordTag WHERE record_tag_id = ?", (tag_id,))
        conn.execute("DELETE FROM runningRecordToRecordTag WHERE record_tag_id = ?", (tag_id,))
        conn.execute("DELETE FROM recordTypeToTag WHERE record_tag_id = ?", (tag_id,))
        conn.execute("DELETE FROM goals WHERE id_type = 'tag' AND id_value = ?", (tag_id,))
        conn.execute("DELETE FROM recordTags WHERE id = ?", (tag_id,))


def get_tags_of_type(type_id: int) -> list[int]:
    """Tags assigned to an activity. General tags (no assignment) apply to all."""
    with connect() as conn:
        return [
            row["record_tag_id"]
            for row in conn.execute(
                "SELECT record_tag_id FROM recordTypeToTag WHERE record_type_id = ?",
                (type_id,),
            )
        ]


def set_types_of_tag(tag_id: int, type_ids: list[int]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM recordTypeToTag WHERE record_tag_id = ?", (tag_id,))
        conn.executemany(
            "INSERT INTO recordTypeToTag (record_type_id, record_tag_id) VALUES (?, ?)",
            [(type_id, tag_id) for type_id in type_ids],
        )


def get_types_of_tag(tag_id: int) -> list[int]:
    with connect() as conn:
        return [
            row["record_type_id"]
            for row in conn.execute(
                "SELECT record_type_id FROM recordTypeToTag WHERE record_tag_id = ?",
                (tag_id,),
            )
        ]


def get_selectable_tags(type_id: int) -> list[RecordTag]:
    """General tags plus the tags assigned to this activity."""
    assigned = set(get_tags_of_type(type_id))
    with connect() as conn:
        typed = {row["record_tag_id"] for row in conn.execute("SELECT record_tag_id FROM recordTypeToTag")}
    return [tag for tag in get_tags() if tag.id in assigned or tag.id not in typed]


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


def _load_record_tags(conn: sqlite3.Connection, record_ids: list[int]) -> dict[int, list[int]]:
    if not record_ids:
        return {}
    placeholders = ",".join("?" * len(record_ids))
    result: dict[int, list[int]] = {}
    for row in conn.execute(
        f"SELECT record_id, record_tag_id FROM recordToRecordTag WHERE record_id IN ({placeholders})",
        record_ids,
    ):
        result.setdefault(row["record_id"], []).append(row["record_tag_id"])
    return result


def get_records(
    time_range: Range | None = None,
    type_ids: list[int] | None = None,
) -> list[Record]:
    """Records overlapping ``time_range`` (all records when it is None/undefined)."""
    query = "SELECT * FROM records"
    params: list[object] = []
    clauses: list[str] = []
    if time_range is not None and not time_range.is_undefined:
        clauses.append("time_started < ? AND time_ended > ?")
        params += [time_range.time_ended, time_range.time_started]
    if type_ids is not None:
        if not type_ids:
            return []
        clauses.append(f"type_id IN ({','.join('?' * len(type_ids))})")
        params += list(type_ids)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY time_started DESC"

    with connect() as conn:
        rows = list(conn.execute(query, params))
        tags = _load_record_tags(conn, [row["id"] for row in rows])
    return [
        Record(
            id=row["id"],
            type_id=row["type_id"],
            time_started=row["time_started"],
            time_ended=row["time_ended"],
            comment=row["comment"],
            tag_ids=tags.get(row["id"], []),
        )
        for row in rows
    ]


def get_record(record_id: int) -> Record | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            return None
        tags = _load_record_tags(conn, [record_id]).get(record_id, [])
    return Record(
        id=row["id"],
        type_id=row["type_id"],
        time_started=row["time_started"],
        time_ended=row["time_ended"],
        comment=row["comment"],
        tag_ids=tags,
    )


def get_first_record_start() -> int | None:
    """Start of the earliest record — the app calculates untracked time from here."""
    with connect() as conn:
        row = conn.execute("SELECT MIN(time_started) AS value FROM records").fetchone()
    return row["value"] if row and row["value"] is not None else None


def _save_record(conn: sqlite3.Connection, record: Record) -> int:
    """Save a record using an existing transaction."""
    record_id = _upsert(
        conn,
        "records",
        record.id,
        {
            "type_id": record.type_id,
            "time_started": record.time_started,
            "time_ended": record.time_ended,
            "comment": record.comment,
        },
    )
    conn.execute("DELETE FROM recordToRecordTag WHERE record_id = ?", (record_id,))
    conn.executemany(
        "INSERT INTO recordToRecordTag (record_id, record_tag_id) VALUES (?, ?)",
        [(record_id, tag_id) for tag_id in record.tag_ids],
    )
    return record_id


def save_record(record: Record) -> int:
    with connect() as conn:
        return _save_record(conn, record)


def delete_record(record_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM recordToRecordTag WHERE record_id = ?", (record_id,))
        conn.execute("DELETE FROM records WHERE id = ?", (record_id,))


# --------------------------------------------------------------------------- #
# Running records
# --------------------------------------------------------------------------- #


def get_running_records() -> list[RunningRecord]:
    with connect() as conn:
        rows = list(conn.execute("SELECT * FROM runningRecords ORDER BY time_started"))
        tags: dict[int, list[int]] = {}
        for row in conn.execute("SELECT * FROM runningRecordToRecordTag"):
            tags.setdefault(row["running_record_id"], []).append(row["record_tag_id"])
    return [
        RunningRecord(
            id=row["id"],
            time_started=row["time_started"],
            comment=row["comment"],
            tag_ids=tags.get(row["id"], []),
        )
        for row in rows
    ]


def get_running_record(type_id: int) -> RunningRecord | None:
    return next((r for r in get_running_records() if r.id == type_id), None)


def start_running_record(
    type_id: int,
    time_started: int | None = None,
    comment: str = "",
    tag_ids: list[int] | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO runningRecords (id, time_started, comment) VALUES (?, ?, ?)",
            (type_id, time_started if time_started is not None else now_ms(), comment),
        )
        conn.execute("DELETE FROM runningRecordToRecordTag WHERE running_record_id = ?", (type_id,))
        conn.executemany(
            "INSERT INTO runningRecordToRecordTag (running_record_id, record_tag_id) VALUES (?, ?)",
            [(type_id, tag_id) for tag_id in (tag_ids or [])],
        )


def update_running_record(record: RunningRecord) -> None:
    start_running_record(
        type_id=record.id,
        time_started=record.time_started,
        comment=record.comment,
        tag_ids=record.tag_ids,
    )


def remove_running_record(type_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM runningRecords WHERE id = ?", (type_id,))
        conn.execute("DELETE FROM runningRecordToRecordTag WHERE running_record_id = ?", (type_id,))


def stop_running_record(type_id: int) -> int | None:
    """Turn a running record into a finished one. Returns the new record id."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM runningRecords WHERE id = ?", (type_id,)).fetchone()
        if row is None:
            return None
        tag_ids = [
            tag["record_tag_id"]
            for tag in conn.execute(
                "SELECT record_tag_id FROM runningRecordToRecordTag "
                "WHERE running_record_id = ?",
                (type_id,),
            )
        ]
        record_id = _save_record(
            conn,
            Record(
                type_id=row["id"],
                time_started=row["time_started"],
                time_ended=now_ms(),
                comment=row["comment"],
                tag_ids=tag_ids,
            ),
        )
        conn.execute("DELETE FROM runningRecordToRecordTag WHERE running_record_id = ?", (type_id,))
        conn.execute("DELETE FROM runningRecords WHERE id = ?", (type_id,))
        return record_id


# --------------------------------------------------------------------------- #
# Goals
# --------------------------------------------------------------------------- #


def get_goals() -> list[Goal]:
    with connect() as conn:
        return [_to_goal(row) for row in conn.execute("SELECT * FROM goals ORDER BY id")]


def save_goal(goal: Goal) -> int:
    days = ",".join(str(d) for d in sorted(goal.days_of_week))
    with connect() as conn:
        return _upsert(
            conn,
            "goals",
            goal.id,
            {
                "id_type": goal.id_type.value,
                "id_value": goal.id_value,
                "range": goal.range.value,
                "type": goal.type.value,
                "value": goal.value,
                "subtype": goal.subtype.value,
                "days_of_week": days,
            },
        )


def delete_goal(goal_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))


# --------------------------------------------------------------------------- #
# Preferences
# --------------------------------------------------------------------------- #

DEFAULT_PREFS: dict[str, str] = {
    "show_untracked": "false",
    "show_seconds": "true",
    "first_day_of_week": "0",  # 0 = Monday
    "start_of_day_shift": "0",  # ms
    "ignore_short_untracked": "0",  # seconds
    "allow_multitasking": "true",
}


def get_prefs() -> dict[str, str]:
    with connect() as conn:
        stored = {row["key"]: row["value"] for row in conn.execute("SELECT * FROM prefs")}
    return {**DEFAULT_PREFS, **stored}


def get_pref(key: str) -> str:
    return get_prefs().get(key, "")


def get_bool_pref(key: str) -> bool:
    return get_pref(key) == "true"


def get_int_pref(key: str) -> int:
    try:
        return int(get_pref(key))
    except ValueError:
        return 0


def set_pref(key: str, value: str | bool | int) -> None:
    if isinstance(value, bool):
        value = "true" if value else "false"
    with connect() as conn:
        conn.execute(
            "INSERT INTO prefs (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
