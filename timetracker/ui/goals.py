"""Goals page — the app's "Goals" tab plus goal editing."""

from __future__ import annotations

import streamlit as st

from .. import repository as repo
from ..domain.duration import HOUR_MS, MINUTE_MS, format_duration, parse_duration
from ..models import Goal, GoalIdType, GoalRange, GoalSubtype, GoalType
from ..service import progress_for_goal
from .common import (
    Entity,
    category_entities,
    goal_progress_bar,
    inject_css,
    tag_entities,
    type_entities,
)

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

ID_TYPE_LABELS = {
    GoalIdType.TYPE: "Activity",
    GoalIdType.CATEGORY: "Category",
    GoalIdType.TAG: "Tag",
}


def render() -> None:
    inject_css()
    st.title("🎯 Goals")

    goals = repo.get_goals()

    with st.expander("➕ Add a goal", expanded=not goals):
        _goal_form(Goal(), key="new")

    if not goals:
        st.info("No goals yet.")
        return

    entities = _entities_for(goals)
    for goal_range in GoalRange:
        in_range = [g for g in goals if g.range is goal_range]
        if not in_range:
            continue
        st.subheader(f"{goal_range.value.capitalize()}")
        for goal in in_range:
            entity = entities.get((goal.id_type, goal.id_value))
            if entity is None:
                continue
            with st.container(border=True):
                progress = progress_for_goal(goal)
                goal_progress_bar(progress, entity, show_seconds=False)
                if not progress.active_today:
                    st.caption(
                        "Not active today · "
                        + ", ".join(DAY_NAMES[d] for d in sorted(goal.days_of_week))
                    )
                with st.expander("Edit"):
                    _goal_form(goal, key=f"goal_{goal.id}")
                    if st.button("Delete goal", key=f"goal_del_{goal.id}"):
                        repo.delete_goal(goal.id)
                        st.rerun()


def _entities_for(goals: list[Goal]) -> dict[tuple[GoalIdType, int], Entity]:
    types = type_entities()
    categories = category_entities()
    tags = tag_entities()
    lookup: dict[tuple[GoalIdType, int], Entity] = {}
    for goal in goals:
        source = {
            GoalIdType.TYPE: types,
            GoalIdType.CATEGORY: categories,
            GoalIdType.TAG: tags,
        }[goal.id_type]
        if goal.id_value in source:
            lookup[(goal.id_type, goal.id_value)] = source[goal.id_value]
    return lookup


def _goal_form(goal: Goal, key: str) -> None:
    types = repo.get_record_types()
    categories = repo.get_categories()
    tags = repo.get_tags()
    if goal.id_type is GoalIdType.TAG:
        current = repo.tags_by_id(include_archived=True).get(goal.id_value)
        if current is not None and current.id not in {tag.id for tag in tags}:
            # Existing archived targets remain selectable while editing. New
            # goals still offer active tags only.
            tags.append(current)

    available = [GoalIdType.TYPE]
    if categories:
        available.append(GoalIdType.CATEGORY)
    if tags:
        available.append(GoalIdType.TAG)

    id_type = st.selectbox(
        "Applies to",
        available,
        index=available.index(goal.id_type) if goal.id_type in available else 0,
        format_func=lambda t: ID_TYPE_LABELS[t],
        key=f"{key}_idtype",
    )

    source = {
        GoalIdType.TYPE: [(t.id, f"{t.icon} {t.name}") for t in types],
        GoalIdType.CATEGORY: [(c.id, c.name) for c in categories],
        GoalIdType.TAG: [(t.id, f"{t.icon} {t.name}") for t in tags],
    }[id_type]
    if not source:
        st.warning("Nothing to attach this goal to yet.")
        return

    ids = [item[0] for item in source]
    names = dict(source)
    id_value = st.selectbox(
        ID_TYPE_LABELS[id_type],
        ids,
        index=ids.index(goal.id_value) if goal.id_value in ids else 0,
        format_func=lambda i: names[i],
        key=f"{key}_idvalue",
    )

    col_range, col_kind, col_subtype = st.columns(3)
    with col_range:
        goal_range = st.selectbox(
            "Period",
            list(GoalRange),
            index=list(GoalRange).index(goal.range),
            format_func=lambda r: r.value.capitalize(),
            key=f"{key}_range",
        )
    with col_kind:
        goal_type = st.selectbox(
            "Measure",
            list(GoalType),
            index=list(GoalType).index(goal.type),
            format_func=lambda t: "Duration" if t is GoalType.DURATION else "Record count",
            key=f"{key}_type",
        )
    with col_subtype:
        subtype = st.selectbox(
            "Kind",
            list(GoalSubtype),
            index=list(GoalSubtype).index(goal.subtype),
            format_func=lambda s: "Goal (reach)" if s is GoalSubtype.GOAL else "Limit (stay under)",
            key=f"{key}_subtype",
        )

    if goal_type is GoalType.DURATION:
        default = goal.value if goal.value else HOUR_MS
        text = st.text_input(
            "Target duration",
            format_duration(default, show_seconds=False),
            help="For example `1h 30m`, `90m` or `1:30`.",
            key=f"{key}_duration",
        )
        parsed = parse_duration(text)
        if parsed is None:
            st.error("Could not read that duration.")
            return
        value = parsed
    else:
        value = st.number_input(
            "Target count",
            min_value=1,
            value=max(goal.value, 1),
            step=1,
            key=f"{key}_count",
        )

    days = set(goal.days_of_week)
    if goal_range is GoalRange.DAILY:
        picked = st.multiselect(
            "Days",
            options=list(range(7)),
            default=sorted(days) or list(range(7)),
            format_func=lambda d: DAY_NAMES[d],
            key=f"{key}_days",
        )
        days = set(picked)

    if st.button("Save goal", type="primary", key=f"{key}_save"):
        if goal_type is GoalType.DURATION and value < MINUTE_MS:
            st.error("Give the goal at least a minute.")
            return
        goal.id_type = id_type
        goal.id_value = id_value
        goal.range = goal_range
        goal.type = goal_type
        goal.value = int(value)
        goal.subtype = subtype
        goal.days_of_week = days or set(range(7))
        repo.save_goal(goal)
        st.rerun()
