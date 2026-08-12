"""Records page — the app's "Records" tab: browse, edit and add records."""

from __future__ import annotations

import html

import streamlit as st

from .. import repository as repo
from ..colors import text_color_for
from ..domain.ranges import split_into_days, start_of_day
from ..domain.statistics import clamp_to_range, records_in_range
from ..models import UNTRACKED_ITEM_ID, Range, Record, now_ms
from ..service import (
    Settings,
    load_settings,
    records_for_range,
    untracked_for_range,
)
from .common import (
    datetime_input,
    duration_text,
    format_day,
    format_time_of_day,
    inject_css,
    range_selector,
    tag_chips,
    tag_entities,
    tag_picker,
    type_entities,
)


def render() -> None:
    inject_css()
    st.title("📋 Records")

    settings = load_settings()
    types = repo.get_record_types()
    if not types:
        st.info("No activities yet. Add one on the **Activities** page.")
        return

    time_range, _ = range_selector("records", settings, default="Day")

    with st.expander("➕ Add a record"):
        _add_record_form(types)

    coverage_records = records_for_range(time_range)
    tracked_records = _apply_filters(coverage_records)
    records = tracked_records

    if settings.show_untracked:
        records = _with_untracked(time_range, records, coverage_records)

    records.sort(key=lambda r: r.time_started, reverse=True)

    if not records:
        st.info("No records in this range.")
        return

    _summary(tracked_records, time_range, settings)
    _timeline(records, time_range, settings)
    _record_list(records, settings)


def _with_untracked(
    time_range: Range,
    displayed_records: list[Record],
    coverage_records: list[Record],
) -> list[Record]:
    """Add gaps based on all tracked time, not just the active UI filters."""
    return displayed_records + untracked_for_range(time_range, coverage_records)


def _apply_filters(records: list[Record]) -> list[Record]:
    entities = type_entities()
    tags = tag_entities()

    col_types, col_tags = st.columns(2)
    with col_types:
        type_ids = st.multiselect(
            "Activities",
            options=[t.id for t in repo.get_record_types()],
            format_func=lambda i: f"{entities[i].icon} {entities[i].name}",
            key="records_filter_types",
        )
    with col_tags:
        tag_ids = st.multiselect(
            "Tags",
            options=[t.id for t in repo.get_tags(include_archived=True)],
            format_func=lambda i: f"{tags[i].icon} {tags[i].name}",
            key="records_filter_tags",
        )

    if type_ids:
        records = [r for r in records if r.type_id in type_ids]
    if tag_ids:
        records = [r for r in records if set(tag_ids) & set(r.tag_ids)]
    return records


def _summary(records: list[Record], time_range: Range, settings: Settings) -> None:
    total, count = _summary_values(records, time_range)
    col_total, col_count = st.columns(2)
    col_total.metric("Total tracked", duration_text(total, settings))
    col_count.metric("Records", count)


def _summary_values(records: list[Record], time_range: Range) -> tuple[int, int]:
    """Tracked-only values, even when display records include pseudo gaps."""
    tracked = [record for record in records if record.type_id != UNTRACKED_ITEM_ID]
    total = sum(
        clamp_to_range(record, time_range).duration
        if not time_range.is_undefined
        else record.duration
        for record in tracked
    )
    return total, len(tracked)


def _timeline(records: list[Record], time_range: Range, settings: Settings) -> None:
    """One horizontal bar per day, with a block for every record."""
    if time_range.is_undefined:
        return
    days = split_into_days(time_range, settings.start_of_day_shift)
    if len(days) > 14:
        return

    entities = type_entities()
    st.caption("Timeline")
    for day in days:
        day_records = records_in_range(records, day)
        blocks = []
        day_duration = day.duration
        for record in sorted(day_records, key=lambda r: r.time_started):
            clamped = clamp_to_range(record, day)
            left = (clamped.time_started - day.time_started) / day_duration * 100
            width = clamped.duration / day_duration * 100
            entity = entities.get(record.type_id)
            if entity is None or width <= 0:
                continue
            title = f"{entity.name} {format_time_of_day(record.time_started)}"
            blocks.append(
                f"<span style='left:{left:.3f}%;width:{max(width, 0.2):.3f}%;"
                f"background:{entity.color}' title='{html.escape(title)}'></span>"
            )
        if len(days) > 1:
            st.caption(format_day(day.time_started, settings.start_of_day_shift))
        st.markdown(f"<div class='stt-timeline'>{''.join(blocks)}</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='stt-hours'><span>00:00</span><span>06:00</span>"
        "<span>12:00</span><span>18:00</span><span>24:00</span></div>",
        unsafe_allow_html=True,
    )


def _record_list(records: list[Record], settings: Settings) -> None:
    entities = type_entities()
    tags = tag_entities()

    current_day: int | None = None
    for record in records:
        day = start_of_day(record.time_started, settings.start_of_day_shift)
        if day != current_day:
            current_day = day
            st.subheader(format_day(day, settings.start_of_day_shift), divider="gray")

        entity = entities.get(record.type_id)
        if entity is None:
            continue

        with st.container(border=True):
            col_info, col_actions = st.columns([5, 1])
            with col_info:
                st.markdown(
                    f"<div class='stt-card' style='background:{entity.color};"
                    f"color:{text_color_for(entity.color)}'>"
                    f"<span style='font-size:1.2em'>{html.escape(entity.icon)}</span>"
                    f"<span>{html.escape(entity.name)}<br><span class='stt-sub'>"
                    f"{format_time_of_day(record.time_started)} – {format_time_of_day(record.time_ended)}"
                    f" · {duration_text(record.duration, settings)}</span></span></div>",
                    unsafe_allow_html=True,
                )
                if record.tag_ids:
                    st.markdown(tag_chips(record.tag_ids, tags), unsafe_allow_html=True)
                if record.comment:
                    st.caption(record.comment)
            with col_actions:
                if record.id:
                    if st.button("🗑", key=f"del_{record.id}", help="Delete record"):
                        repo.delete_record(record.id)
                        st.rerun()

            if record.id:
                with st.expander("Edit"):
                    _edit_record_form(record)


def _edit_record_form(record: Record) -> None:
    types = repo.get_record_types()
    type_ids = [t.id for t in types]
    entities = type_entities()

    type_id = st.selectbox(
        "Activity",
        type_ids,
        index=type_ids.index(record.type_id) if record.type_id in type_ids else 0,
        format_func=lambda i: f"{entities[i].icon} {entities[i].name}",
        key=f"edit_type_{record.id}",
    )
    start = datetime_input("Start", record.time_started, key=f"edit_start_{record.id}")
    end = datetime_input("End", record.time_ended, key=f"edit_end_{record.id}")
    comment = st.text_input("Comment", record.comment, key=f"edit_comment_{record.id}")
    tag_ids = tag_picker("Tags", type_id, record.tag_ids, key=f"edit_tags_{record.id}")

    if st.button("Save changes", key=f"edit_save_{record.id}", type="primary"):
        if start is None or end is None:
            st.error("Enter a valid date and time.")
            return
        if end <= start:
            st.error("The end has to be after the start.")
            return
        record.type_id = type_id
        record.time_started = start
        record.time_ended = end
        record.comment = comment
        record.tag_ids = tag_ids
        repo.save_record(record)
        st.rerun()


def _add_record_form(types) -> None:
    entities = type_entities()
    type_ids = [t.id for t in types]

    type_id = st.selectbox(
        "Activity",
        type_ids,
        format_func=lambda i: f"{entities[i].icon} {entities[i].name}",
        key="add_type",
    )
    default_end = now_ms()
    start = datetime_input("Start", default_end - 3600_000, key="add_start")
    end = datetime_input("End", default_end, key="add_end")
    comment = st.text_input("Comment", key="add_comment")
    tag_ids = tag_picker("Tags", type_id, [], key="add_tags")

    if st.button("Add record", type="primary", key="add_record"):
        if start is None or end is None:
            st.error("Enter a valid date and time.")
            return
        if end <= start:
            st.error("The end has to be after the start.")
            return
        repo.save_record(
            Record(
                type_id=type_id,
                time_started=start,
                time_ended=end,
                comment=comment,
                tag_ids=tag_ids,
            )
        )
        st.rerun()
