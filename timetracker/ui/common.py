"""Shared widgets and formatting helpers for the Streamlit pages."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, datetime, time

import streamlit as st

from .. import repository as repo
from ..colors import COLOR_NAMES, COLORS, UNTRACKED_COLOR, AppColor, text_color_for
from ..domain.duration import format_duration
from ..domain.goals import GoalProgress
from ..domain.ranges import (
    RangeLength,
    day_range,
    format_range,
    shift_timestamp,
    to_datetime,
    to_ms,
)
from ..icons import ICONS, UNTRACKED_ICON
from ..models import (
    UNCATEGORIZED_ITEM_ID,
    UNTRACKED_ITEM_ID,
    Category,
    GoalSubtype,
    Range,
    RecordTag,
    RecordType,
)
from ..service import Settings, current_range

CSS = """
<style>
    .stt-card {
        border-radius: 10px;
        padding: 10px 12px;
        margin-bottom: 6px;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 8px;
        line-height: 1.3;
    }
    .stt-card .stt-sub {
        font-weight: 400;
        opacity: 0.85;
        font-size: 0.82em;
    }
    .stt-chip {
        display: inline-block;
        border-radius: 999px;
        padding: 1px 10px;
        margin: 0 4px 4px 0;
        font-size: 0.78em;
        white-space: nowrap;
    }
    .stt-running {
        box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.35) inset;
    }
    .stt-timeline {
        position: relative;
        height: 26px;
        border-radius: 6px;
        background: rgba(128, 128, 128, 0.15);
        overflow: hidden;
        margin-bottom: 4px;
    }
    .stt-timeline span {
        position: absolute;
        top: 0;
        height: 100%;
    }
    .stt-hours {
        display: flex;
        justify-content: space-between;
        font-size: 0.7em;
        opacity: 0.6;
    }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Display helpers
# --------------------------------------------------------------------------- #


@dataclass
class Entity:
    """Anything that can be shown as a colored chip: activity, category or tag."""

    id: int
    name: str
    icon: str
    color: str


UNTRACKED_ENTITY = Entity(UNTRACKED_ITEM_ID, "Untracked", UNTRACKED_ICON, UNTRACKED_COLOR)
UNCATEGORIZED_ENTITY = Entity(UNCATEGORIZED_ITEM_ID, "Uncategorized", "❔", UNTRACKED_COLOR)


def type_entity(record_type: RecordType) -> Entity:
    return Entity(record_type.id, record_type.name, record_type.icon, record_type.color.hex)


def category_entity(category: Category) -> Entity:
    return Entity(category.id, category.name, "🗂️", category.color.hex)


def tag_entity(tag: RecordTag, types: dict[int, RecordType] | None = None) -> Entity:
    color = tag.color.hex
    if tag.icon_color_source and types:
        source = types.get(tag.icon_color_source)
        if source:
            color = source.color.hex
    return Entity(tag.id, tag.name, tag.icon, color)


def type_entities() -> dict[int, Entity]:
    entities = {t.id: type_entity(t) for t in repo.get_record_types()}
    entities[UNTRACKED_ITEM_ID] = UNTRACKED_ENTITY
    return entities


def category_entities() -> dict[int, Entity]:
    entities = {c.id: category_entity(c) for c in repo.get_categories()}
    entities[UNCATEGORIZED_ITEM_ID] = UNCATEGORIZED_ENTITY
    entities[UNTRACKED_ITEM_ID] = UNTRACKED_ENTITY
    return entities


def tag_entities() -> dict[int, Entity]:
    types = repo.record_types_by_id()
    entities = {t.id: tag_entity(t, types) for t in repo.get_tags(include_archived=True)}
    entities[UNCATEGORIZED_ITEM_ID] = Entity(UNCATEGORIZED_ITEM_ID, "Untagged", "❔", UNTRACKED_COLOR)
    entities[UNTRACKED_ITEM_ID] = UNTRACKED_ENTITY
    return entities


def entities_for_filter(filter_name: str) -> dict[int, Entity]:
    if filter_name == "category":
        return category_entities()
    if filter_name == "tag":
        return tag_entities()
    return type_entities()


def card(entity: Entity, subtitle: str = "", running: bool = False) -> str:
    background = entity.color
    classes = "stt-card stt-running" if running else "stt-card"
    sub = f"<span class='stt-sub'>{html.escape(subtitle)}</span>" if subtitle else ""
    return (
        f"<div class='{classes}' style='background:{background};color:{text_color_for(background)}'>"
        f"<span style='font-size:1.3em'>{html.escape(entity.icon)}</span>"
        f"<span>{html.escape(entity.name)}<br>{sub}</span></div>"
    )


def chip(entity: Entity, text: str | None = None) -> str:
    background = entity.color
    label = text if text is not None else f"{entity.icon} {entity.name}"
    return (
        f"<span class='stt-chip' style='background:{background};"
        f"color:{text_color_for(background)}'>{html.escape(label)}</span>"
    )


def tag_chips(tag_ids: list[int], tags: dict[int, Entity]) -> str:
    return "".join(chip(tags[tag_id]) for tag_id in tag_ids if tag_id in tags)


# --------------------------------------------------------------------------- #
# Pickers
# --------------------------------------------------------------------------- #


def color_picker(label: str, current: AppColor, key: str) -> AppColor:
    options = COLOR_NAMES + ["Custom…"]
    index = current.color_id if not current.color_int else len(COLOR_NAMES)
    choice = st.selectbox(label, options, index=min(index, len(options) - 1), key=f"{key}_name")
    if choice == "Custom…":
        picked = st.color_picker(
            "Custom color", current.hex, key=f"{key}_custom", label_visibility="collapsed"
        )
        return AppColor(color_id=0, color_int=picked.upper())
    color_id = COLOR_NAMES.index(choice)
    st.markdown(
        f"<div style='height:8px;border-radius:4px;background:{COLORS[color_id]}'></div>",
        unsafe_allow_html=True,
    )
    return AppColor(color_id=color_id, color_int="")


def icon_picker(label: str, current: str, key: str) -> str:
    groups = list(ICONS)
    current_group = next((g for g, icons in ICONS.items() if current in icons), groups[0])
    group = st.selectbox(label, groups, index=groups.index(current_group), key=f"{key}_group")
    icons = ICONS[group]
    index = icons.index(current) if current in icons else 0
    return st.radio(
        "Icon",
        icons,
        index=index,
        horizontal=True,
        key=f"{key}_icon",
        label_visibility="collapsed",
    )


def tag_picker(label: str, type_id: int, selected: list[int], key: str) -> list[int]:
    lookup = {tag.id: tag for tag in repo.get_selectable_tags(type_id)}
    all_tags = repo.tags_by_id(include_archived=True)
    # Existing record tags remain editable even after being archived or
    # reassigned to another activity. Otherwise an unrelated edit would
    # silently delete them.
    for tag_id in selected:
        if tag_id in all_tags:
            lookup.setdefault(tag_id, all_tags[tag_id])
    if not lookup:
        return []

    def label_for(tag_id: int) -> str:
        tag = lookup[tag_id]
        suffix = " (archived)" if tag.archived else ""
        return f"{tag.icon} {tag.name}{suffix}"

    chosen = st.multiselect(
        label,
        options=list(lookup),
        default=[t for t in selected if t in lookup],
        format_func=label_for,
        key=key,
    )
    return list(chosen)


def datetime_input(label: str, value: int, key: str) -> int | None:
    """A date + time pair, as a millisecond timestamp.

    The time field lists quarter hours, but it is a combobox: typing an exact
    time such as ``8:07`` selects it. ``None`` means the fields do not hold a
    usable moment (a cleared date) — callers must not save then.
    """
    moment = to_datetime(value)
    col_date, col_time = st.columns(2)
    with col_date:
        picked_date: date | None = st.date_input(label, moment.date(), key=f"{key}_date")
    with col_time:
        picked_time: time = st.time_input(
            "Time",
            moment.time().replace(microsecond=0),
            key=f"{key}_time",
            help="Type an exact time, for example 8:07.",
            label_visibility="hidden",
        )

    if picked_date is None:
        st.caption("⚠️ Pick a date.")
        return None
    return to_ms(datetime.combine(picked_date, picked_time))


# --------------------------------------------------------------------------- #
# Range selector
# --------------------------------------------------------------------------- #

RANGE_LABELS: dict[str, RangeLength] = {
    "Day": RangeLength.DAY,
    "Week": RangeLength.WEEK,
    "Month": RangeLength.MONTH,
    "Year": RangeLength.YEAR,
    "Last 7 days": RangeLength.LAST,
    "All": RangeLength.ALL,
    "Custom": RangeLength.CUSTOM,
}


def range_selector(key: str, settings: Settings, default: str = "Day") -> tuple[Range, str]:
    """Range picker with previous/next navigation, like the app's range header."""
    labels = list(RANGE_LABELS)
    shift_key = f"{key}_shift"
    st.session_state.setdefault(shift_key, 0)

    choice = st.segmented_control(
        "Range",
        labels,
        default=default,
        key=f"{key}_length",
        label_visibility="collapsed",
    )
    choice = choice or default
    length = RANGE_LABELS[choice]

    custom: Range | None = None
    if length is RangeLength.CUSTOM:
        today = datetime.now().date()
        picked = st.date_input(
            "Custom range",
            value=(today, today),
            key=f"{key}_custom",
        )
        if isinstance(picked, tuple) and len(picked) == 2:
            start, end = picked
            custom = Range(
                day_range(start, settings.start_of_day_shift).time_started,
                day_range(end, settings.start_of_day_shift).time_ended,
            )
        else:
            custom = Range(0, 0)

    navigable = length in (RangeLength.DAY, RangeLength.WEEK, RangeLength.MONTH, RangeLength.YEAR)
    if not navigable:
        st.session_state[shift_key] = 0

    if navigable:
        col_prev, col_title, col_next = st.columns([1, 6, 1])
        with col_prev:
            if st.button("◀", key=f"{key}_prev", use_container_width=True):
                st.session_state[shift_key] -= 1
        with col_next:
            disabled = st.session_state[shift_key] >= 0
            if st.button("▶", key=f"{key}_next", use_container_width=True, disabled=disabled):
                st.session_state[shift_key] += 1
    else:
        col_title = st.container()

    time_range = current_range(
        length,
        shift=st.session_state[shift_key],
        last_days=7,
        custom=custom,
        settings=settings,
    )
    title = format_range(length, time_range, settings.start_of_day_shift)
    with col_title:
        st.markdown(f"<div style='text-align:center;font-weight:600'>{title}</div>", unsafe_allow_html=True)
    return time_range, title


# --------------------------------------------------------------------------- #
# Goals
# --------------------------------------------------------------------------- #


def goal_progress_bar(progress: GoalProgress, entity: Entity, show_seconds: bool = True) -> None:
    goal = progress.goal
    is_limit = goal.subtype is GoalSubtype.LIMIT
    caption = f"{goal.range.value.capitalize()} {'limit' if is_limit else 'goal'}"

    if is_limit:
        status = "🚫 over limit" if progress.exceeded_limit else "✅ within limit"
    else:
        status = "✅ reached" if progress.reached else f"{progress.format_value(progress.left, show_seconds)} left"

    st.markdown(
        f"{chip(entity)} <span style='opacity:0.7'>{caption}</span> — "
        f"<b>{progress.describe(show_seconds)}</b> · {status}",
        unsafe_allow_html=True,
    )
    st.progress(min(progress.percent / 100, 1.0))


def format_time_of_day(timestamp: int) -> str:
    return to_datetime(timestamp).strftime("%H:%M")


def format_day(timestamp: int, start_of_day_shift: int = 0) -> str:
    logical = shift_timestamp(timestamp, -start_of_day_shift)
    return to_datetime(logical).strftime("%a, %d %b %Y")


def duration_text(duration: int, settings: Settings) -> str:
    return format_duration(duration, settings.show_seconds)
