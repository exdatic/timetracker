"""Timers page — the app's "Running records" tab."""

from __future__ import annotations

import streamlit as st

from .. import repository as repo
from ..domain.duration import format_timer
from ..models import Record, RecordType, now_ms
from ..service import goals_of_type, load_settings, progress_for_goal, start_activity
from .common import (
    card,
    duration_text,
    format_time_of_day,
    inject_css,
    tag_chips,
    tag_entities,
    tag_picker,
    type_entity,
)

COLUMNS = 3


def render() -> None:
    inject_css()
    st.title("⏱️ Timers")

    settings = load_settings()
    types = repo.get_record_types(include_hidden=False)
    if not types:
        st.info("No activities yet. Add one on the **Activities** page.")
        return

    _running_section()
    st.divider()
    _activity_grid(types, settings)


def _running_section() -> None:
    """Cards for everything that is currently running."""
    running = repo.get_running_records()
    if not running:
        st.caption("Nothing is running. Pick an activity below to start tracking.")
        return

    types = repo.record_types_by_id()
    tags = tag_entities()

    st.subheader("Running now")
    for row_start in range(0, len(running), COLUMNS):
        columns = st.columns(COLUMNS)
        row = running[row_start:row_start + COLUMNS]
        for column, record in zip(columns, row):
            record_type = types.get(record.id)
            if record_type is None:
                continue
            with column, st.container(border=True):
                st.markdown(
                    card(
                        type_entity(record_type),
                        subtitle=f"since {format_time_of_day(record.time_started)}",
                        running=True,
                    ),
                    unsafe_allow_html=True,
                )
                _live_timer(record.time_started)
                if record.tag_ids:
                    st.markdown(tag_chips(record.tag_ids, tags), unsafe_allow_html=True)
                if record.comment:
                    st.caption(record.comment)

                col_stop, col_cancel = st.columns(2)
                with col_stop:
                    if st.button("⏹ Stop", key=f"stop_{record.id}", use_container_width=True, type="primary"):
                        repo.stop_running_record(record.id)
                        st.rerun()
                with col_cancel:
                    if st.button("✕ Discard", key=f"cancel_{record.id}", use_container_width=True):
                        repo.remove_running_record(record.id)
                        st.rerun()

                with st.expander("Edit"):
                    comment = st.text_input("Comment", record.comment, key=f"rr_comment_{record.id}")
                    tag_ids = tag_picker("Tags", record.id, record.tag_ids, key=f"rr_tags_{record.id}")
                    if st.button("Save", key=f"rr_save_{record.id}"):
                        record.comment = comment
                        record.tag_ids = tag_ids
                        repo.update_running_record(record)
                        st.rerun()


@st.fragment(run_every="1s")
def _live_timer(time_started: int) -> None:
    """The ticking clock, and nothing else.

    Only display goes in here: a fragment that reruns on a timer resubmits the
    widget state around it, which fires buttons nobody pressed.
    """
    st.markdown(f"### {format_timer(now_ms() - time_started)}")


def _activity_grid(types: list[RecordType], settings) -> None:
    st.subheader("Activities")

    categories = repo.get_categories()
    if categories:
        names = {category.id: category.name for category in categories}
        options = [0, *names]
        selected = st.segmented_control(
            "Filter",
            options,
            default=0,
            format_func=lambda category_id: "All" if category_id == 0 else names[category_id],
            key="timers_filter",
        )
        if selected:
            allowed = set(repo.get_types_of_category(selected))
            types = [t for t in types if t.id in allowed]

    running_ids = {r.id for r in repo.get_running_records()}

    # A fresh row of columns per chunk, so cards line up instead of stacking
    # unevenly inside three long columns.
    for row_start in range(0, len(types), COLUMNS):
        columns = st.columns(COLUMNS)
        row = types[row_start:row_start + COLUMNS]
        for column, record_type in zip(columns, row):
            with column, st.container(border=True):
                is_running = record_type.id in running_ids
                st.markdown(
                    card(type_entity(record_type), subtitle=_today_subtitle(record_type, settings)),
                    unsafe_allow_html=True,
                )
                _goals_preview(record_type)

                if is_running:
                    if st.button("⏹ Stop", key=f"grid_stop_{record_type.id}", use_container_width=True):
                        repo.stop_running_record(record_type.id)
                        st.rerun()
                elif st.button("▶ Start", key=f"grid_start_{record_type.id}", use_container_width=True):
                    start_activity(record_type.id)
                    st.rerun()

                with st.popover("Add past record", use_container_width=True):
                    _quick_record_form(record_type)


def _today_subtitle(record_type: RecordType, settings) -> str:
    """Time tracked today for this activity, as shown under the activity name."""
    from ..domain.ranges import RangeLength
    from ..domain.statistics import total_duration
    from ..service import current_range, records_for_range

    today = current_range(RangeLength.DAY, settings=settings)
    records = [r for r in records_for_range(today) if r.type_id == record_type.id]
    total = total_duration(today, records, show_seconds=settings.show_seconds)
    return f"today: {duration_text(total, settings)}" if total else "today: –"


def _goals_preview(record_type: RecordType) -> None:
    for goal in goals_of_type(record_type.id):
        progress = progress_for_goal(goal)
        if not progress.active_today:
            continue
        label = f"{goal.range.value} {goal.subtype.value}"
        st.progress(
            min(progress.percent / 100, 1.0),
            text=f"{label}: {progress.describe(show_seconds=False)}",
        )


def _quick_record_form(record_type: RecordType) -> None:
    """Record something that already happened, without running a timer."""
    from .common import datetime_input

    default_end = now_ms()
    default_start = default_end - (record_type.default_duration or 3600_000)

    start = datetime_input("Start", default_start, key=f"quick_start_{record_type.id}")
    end = datetime_input("End", default_end, key=f"quick_end_{record_type.id}")
    comment = st.text_input("Comment", key=f"quick_comment_{record_type.id}")
    tag_ids = tag_picker("Tags", record_type.id, [], key=f"quick_tags_{record_type.id}")

    if st.button("Add record", key=f"quick_add_{record_type.id}", type="primary"):
        if start is None or end is None:
            st.error("Enter a valid date and time.")
            return
        if end <= start:
            st.error("The end has to be after the start.")
            return
        repo.save_record(
            Record(
                type_id=record_type.id,
                time_started=start,
                time_ended=end,
                comment=comment,
                tag_ids=tag_ids,
            )
        )
        st.success("Record added.")
        st.rerun()
