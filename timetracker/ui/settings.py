"""Settings page — preferences, backup and demo data."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from .. import repository as repo
from ..colors import AppColor
from ..db import database_lock, db_path, reset_database, schema_lock, use_database
from ..domain.duration import MINUTE_MS, format_duration
from ..domain.ranges import to_datetime
from ..models import (
    Category,
    Goal,
    GoalIdType,
    GoalRange,
    GoalSubtype,
    GoalType,
    Record,
    RecordTag,
    RecordType,
    TagValueType,
)
from ..seed import database_is_empty, seed_demo_data
from .common import inject_css

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

BACKUP_VERSION = 1
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass
class BackupData:
    record_types: list[RecordType]
    categories: list[Category]
    tags: list[RecordTag]
    records: list[Record]
    running_records: list[dict]
    goals: list[Goal]
    type_categories: list[tuple[int, int]]
    type_tags: list[tuple[int, int]]
    prefs: dict[str, str]


def render() -> None:
    inject_css()
    st.title("⚙️ Settings")

    _preferences()
    st.divider()
    _backup()
    st.divider()
    _danger_zone()


def _preferences() -> None:
    prefs = repo.get_prefs()
    st.subheader("Display")

    show_untracked = st.toggle(
        "Show untracked time",
        value=prefs["show_untracked"] == "true",
        help="Adds the gaps between records to statistics and lists.",
    )
    show_seconds = st.toggle("Show seconds", value=prefs["show_seconds"] == "true")

    st.subheader("Time")
    first_day = st.selectbox(
        "First day of the week",
        options=list(range(7)),
        index=int(prefs["first_day_of_week"]),
        format_func=lambda d: DAY_NAMES[d],
    )
    shift_minutes = st.number_input(
        "Start of the day shift (minutes)",
        min_value=-720,
        max_value=720,
        value=int(prefs["start_of_day_shift"]) // MINUTE_MS,
        step=30,
        help="Shifts day boundaries — useful when your day ends after midnight.",
    )
    cutoff = st.number_input(
        "Ignore untracked gaps shorter than (seconds)",
        min_value=0,
        value=int(prefs["ignore_short_untracked"]),
        step=60,
    )

    st.subheader("Tracking")
    multitasking = st.toggle(
        "Allow multitasking",
        value=prefs["allow_multitasking"] == "true",
        help="When off, starting an activity stops whatever else is running.",
    )

    if st.button("Save settings", type="primary"):
        repo.set_pref("show_untracked", show_untracked)
        repo.set_pref("show_seconds", show_seconds)
        repo.set_pref("first_day_of_week", int(first_day))
        repo.set_pref("start_of_day_shift", int(shift_minutes) * MINUTE_MS)
        repo.set_pref("ignore_short_untracked", int(cutoff))
        repo.set_pref("allow_multitasking", multitasking)
        st.success("Saved.")
        st.rerun()


# --------------------------------------------------------------------------- #
# Backup
# --------------------------------------------------------------------------- #


def export_backup() -> dict:
    """Everything in the database, in a JSON-serialisable shape."""
    return {
        "version": BACKUP_VERSION,
        "record_types": [_dump(t) for t in repo.get_record_types()],
        "categories": [_dump(c) for c in repo.get_categories()],
        "tags": [_dump(t) for t in repo.get_tags(include_archived=True)],
        "records": [_dump(r) for r in repo.get_records()],
        "running_records": [_dump(r) for r in repo.get_running_records()],
        "goals": [_dump(g) for g in repo.get_goals()],
        "type_categories": repo.get_type_category_links(),
        "type_tags": [
            (type_id, tag.id)
            for tag in repo.get_tags(include_archived=True)
            for type_id in repo.get_types_of_tag(tag.id)
        ],
        "prefs": repo.get_prefs(),
    }


def _dump(entity) -> dict:
    data = asdict(entity)
    for key, value in list(data.items()):
        if isinstance(value, set):
            data[key] = sorted(value)
        elif hasattr(value, "value") and not isinstance(value, (int, str)):
            data[key] = value.value
    return data


def import_backup(payload: dict) -> None:
    """Validate and atomically replace the database with a backup."""
    data = _parse_backup(payload)
    destination = db_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".restore", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        # Build the replacement database first, then swap it in atomically.
        # Only the swap itself blocks live readers, so the app stays
        # responsive while a large backup is being written.
        with schema_lock():
            with use_database(temporary):
                reset_database()
                _write_backup(data)
            with database_lock():
                os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _write_backup(data: BackupData) -> None:
    for record_type in data.record_types:
        repo.save_record_type(record_type)
    for category in data.categories:
        repo.save_category(category)
    for tag in data.tags:
        repo.save_tag(tag)
    for record in data.records:
        repo.save_record(record)
    for item in data.running_records:
        repo.start_running_record(**item)
    for goal in data.goals:
        repo.save_goal(goal)

    links: dict[int, list[int]] = {}
    for type_id, category_id in data.type_categories:
        links.setdefault(type_id, []).append(category_id)
    for type_id, category_ids in links.items():
        repo.set_categories_of_type(type_id, category_ids)

    tag_links: dict[int, list[int]] = {}
    for type_id, tag_id in data.type_tags:
        tag_links.setdefault(tag_id, []).append(type_id)
    for tag_id, type_ids in tag_links.items():
        repo.set_types_of_tag(tag_id, type_ids)

    for key, value in data.prefs.items():
        repo.set_pref(key, value)


def _parse_backup(payload: dict) -> BackupData:
    if not isinstance(payload, dict):
        raise ValueError("Backup root must be an object.")
    if payload.get("version") != BACKUP_VERSION:
        raise ValueError(f"Unsupported backup version: {payload.get('version')!r}.")

    items = {name: _object_list(payload, name) for name in (
        "record_types", "categories", "tags", "records", "running_records", "goals"
    )}

    record_types = [
        RecordType(
            id=_integer(item, "id"),
            name=_text(item, "name"),
            icon=_text(item, "icon"),
            color=_color(item),
            default_duration=_integer(item, "default_duration", 0),
            note=_text(item, "note", ""),
            hidden=_boolean(item, "hidden", False),
        )
        for item in items["record_types"]
    ]
    categories = [
        Category(
            id=_integer(item, "id"),
            name=_text(item, "name"),
            color=_color(item),
            note=_text(item, "note", ""),
        )
        for item in items["categories"]
    ]
    tags = [
        RecordTag(
            id=_integer(item, "id"),
            name=_text(item, "name"),
            icon=_text(item, "icon"),
            color=_color(item),
            icon_color_source=_integer(item, "icon_color_source", 0),
            note=_text(item, "note", ""),
            archived=_boolean(item, "archived", False),
            value_type=TagValueType(item.get("value_type", "none")),
            value_suffix=_text(item, "value_suffix", ""),
        )
        for item in items["tags"]
    ]
    records = [
        Record(
            id=_integer(item, "id"),
            type_id=_integer(item, "type_id"),
            time_started=_integer(item, "time_started"),
            time_ended=_integer(item, "time_ended"),
            comment=_text(item, "comment", ""),
            tag_ids=_integer_list(item, "tag_ids"),
        )
        for item in items["records"]
    ]
    running_records = [
        {
            "type_id": _integer(item, "id"),
            "time_started": _integer(item, "time_started"),
            "comment": _text(item, "comment", ""),
            "tag_ids": _integer_list(item, "tag_ids"),
        }
        for item in items["running_records"]
    ]
    goals = [
        Goal(
            id=_integer(item, "id"),
            id_type=GoalIdType(item["id_type"]),
            id_value=_integer(item, "id_value"),
            range=GoalRange(item["range"]),
            type=GoalType(item["type"]),
            value=_integer(item, "value"),
            subtype=GoalSubtype(item["subtype"]),
            days_of_week=set(_integer_list(item, "days_of_week", list(range(7)))),
        )
        for item in items["goals"]
    ]

    type_ids = _ids(record_types, "activities")
    category_ids = _ids(categories, "categories")
    tag_ids = _ids(tags, "tags")
    _ids(records, "records")
    _ids(goals, "goals")

    for record in records:
        _reference(record.type_id, type_ids, "record activity")
        _references(record.tag_ids, tag_ids, "record tag")
        if record.time_ended <= record.time_started:
            raise ValueError(f"Record {record.id} must end after it starts.")
    for running in running_records:
        _reference(running["type_id"], type_ids, "running activity")
        _references(running["tag_ids"], tag_ids, "running tag")
    if len({item["type_id"] for item in running_records}) != len(running_records):
        raise ValueError("Running activity ids must be unique.")
    for tag in tags:
        if tag.icon_color_source:
            _reference(tag.icon_color_source, type_ids, "tag color source")
    for goal in goals:
        target_ids = {
            GoalIdType.TYPE: type_ids,
            GoalIdType.CATEGORY: category_ids,
            GoalIdType.TAG: tag_ids,
        }[goal.id_type]
        _reference(goal.id_value, target_ids, "goal target")
        if goal.value <= 0 or not goal.days_of_week <= set(range(7)):
            raise ValueError(f"Goal {goal.id} has an invalid value or weekday.")

    type_categories = _links(payload, "type_categories", type_ids, category_ids)
    type_tags = _links(payload, "type_tags", type_ids, tag_ids)
    prefs = _prefs(payload.get("prefs", {}))
    return BackupData(
        record_types, categories, tags, records, running_records, goals,
        type_categories, type_tags, prefs,
    )


def _object_list(payload: dict, key: str) -> list[dict]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{key} must be a list of objects.")
    return value


def _integer(item: dict, key: str, default=None) -> int:
    value = item.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer.")
    return value


def _text(item: dict, key: str, default=None) -> str:
    value = item.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text.")
    return value


def _boolean(item: dict, key: str, default: bool) -> bool:
    value = item.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false.")
    return value


def _integer_list(item: dict, key: str, default=None) -> list[int]:
    value = item.get(key, [] if default is None else default)
    if not isinstance(value, list) or any(isinstance(v, bool) or not isinstance(v, int) for v in value):
        raise ValueError(f"{key} must be a list of integers.")
    if len(set(value)) != len(value):
        raise ValueError(f"{key} must not contain duplicates.")
    return value


def _color(item: dict) -> AppColor:
    value = item.get("color")
    if not isinstance(value, dict):
        raise ValueError("color must be an object.")
    color = AppColor(
        color_id=_integer(value, "color_id", 0),
        color_int=_text(value, "color_int", ""),
    )
    if color.color_int and not HEX_COLOR.fullmatch(color.color_int):
        raise ValueError(f"Invalid custom color: {color.color_int!r}.")
    return color


def _ids(entities: list, label: str) -> set[int]:
    values = [entity.id for entity in entities]
    if any(value <= 0 for value in values) or len(set(values)) != len(values):
        raise ValueError(f"{label} must have unique positive ids.")
    return set(values)


def _reference(value: int, available: set[int], label: str) -> None:
    if value not in available:
        raise ValueError(f"Unknown {label} id: {value}.")


def _references(values: list[int], available: set[int], label: str) -> None:
    for value in values:
        _reference(value, available, label)


def _links(payload: dict, key: str, left: set[int], right: set[int]) -> list[tuple[int, int]]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list.")
    result: list[tuple[int, int]] = []
    for pair in value:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f"Each {key} entry must contain two ids.")
        left_id, right_id = pair
        if any(isinstance(item, bool) or not isinstance(item, int) for item in pair):
            raise ValueError(f"Each {key} entry must contain integer ids.")
        _reference(left_id, left, key)
        _reference(right_id, right, key)
        result.append((left_id, right_id))
    if len(set(result)) != len(result):
        raise ValueError(f"{key} must not contain duplicate links.")
    return result


def _prefs(value) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("prefs must be an object.")
    unknown = set(value) - set(repo.DEFAULT_PREFS)
    if unknown:
        raise ValueError(f"Unknown preferences: {', '.join(sorted(unknown))}.")
    prefs = {**repo.DEFAULT_PREFS, **value}
    if any(not isinstance(item, str) for item in prefs.values()):
        raise ValueError("Preference values must be text.")
    if prefs["show_untracked"] not in {"true", "false"}:
        raise ValueError("Invalid show_untracked preference.")
    if prefs["show_seconds"] not in {"true", "false"}:
        raise ValueError("Invalid show_seconds preference.")
    if prefs["allow_multitasking"] not in {"true", "false"}:
        raise ValueError("Invalid allow_multitasking preference.")
    first_day = int(prefs["first_day_of_week"])
    shift = int(prefs["start_of_day_shift"])
    cutoff = int(prefs["ignore_short_untracked"])
    if first_day not in range(7) or not -720 * MINUTE_MS <= shift <= 720 * MINUTE_MS or cutoff < 0:
        raise ValueError("Invalid time preference.")
    return prefs


def _backup() -> None:
    st.subheader("Backup")
    st.caption(f"Database: `{db_path()}`")

    col_json, col_csv = st.columns(2)
    with col_json:
        st.download_button(
            "⬇️ Export backup (JSON)",
            json.dumps(export_backup(), indent=2).encode(),
            file_name="timetracker-backup.json",
            mime="application/json",
            use_container_width=True,
        )
    with col_csv:
        st.download_button(
            "⬇️ Export records (CSV)",
            _records_csv(),
            file_name="timetracker-records.csv",
            mime="text/csv",
            use_container_width=True,
        )

    uploaded = st.file_uploader("Restore a backup", type=["json"])
    if uploaded is not None and st.button("Restore — this replaces everything", type="primary"):
        try:
            import_backup(json.loads(uploaded.getvalue().decode()))
        except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
            st.error(f"That file could not be read: {error}")
        else:
            st.success("Backup restored.")
            st.rerun()


def _records_csv() -> bytes:
    types = repo.record_types_by_id()
    tags = repo.tags_by_id()
    rows = [
        {
            "activity": types[r.type_id].name if r.type_id in types else str(r.type_id),
            "start": to_datetime(r.time_started).isoformat(timespec="seconds"),
            "end": to_datetime(r.time_ended).isoformat(timespec="seconds"),
            "duration": format_duration(r.duration),
            "duration_minutes": round(r.duration / MINUTE_MS, 1),
            "comment": r.comment,
            "tags": ", ".join(tags[t].name for t in r.tag_ids if t in tags),
        }
        for r in sorted(repo.get_records(), key=lambda r: r.time_started)
    ]
    return pd.DataFrame(rows).to_csv(index=False).encode()


# --------------------------------------------------------------------------- #
# Danger zone
# --------------------------------------------------------------------------- #


def _danger_zone() -> None:
    st.subheader("Data")

    col_seed, col_reset = st.columns(2)
    with col_seed:
        days = st.number_input("Days of demo history", min_value=1, max_value=365, value=30)
        empty = database_is_empty()
        if not empty:
            st.caption("Demo data can only be loaded into an empty database.")
        if st.button("Load demo data", use_container_width=True, disabled=not empty):
            seed_demo_data(days=int(days))
            st.success("Demo data added.")
            st.rerun()
    with col_reset:
        st.write("")
        st.write("")
        confirm = st.checkbox("I want to delete everything")
        if st.button("Reset database", disabled=not confirm, use_container_width=True):
            reset_database()
            st.success("Database cleared.")
            st.rerun()
