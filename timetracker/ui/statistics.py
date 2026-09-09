"""Statistics page — the app's "Statistics" tab, with charts instead of a list."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..domain.duration import HOUR_MS, format_duration
from ..domain.ranges import shift_timestamp, split_into_days, to_datetime
from ..domain.statistics import (
    ChartFilterType,
    clamp_to_range,
    duration_in_range,
    records_in_range,
)
from ..models import UNTRACKED_ITEM_ID, Range, Record
from ..service import Settings, load_settings, statistics_for_range
from .common import (
    Entity,
    chip,
    duration_text,
    entities_for_filter,
    inject_css,
    range_selector,
)

GRID_COLOR = "rgba(128,128,128,0.18)"
SURFACE = "rgba(0,0,0,0)"

FILTER_TYPES: dict[str, ChartFilterType] = {
    "Activities": ChartFilterType.ACTIVITY,
    "Categories": ChartFilterType.CATEGORY,
    "Tags": ChartFilterType.TAG,
}


def render() -> None:
    inject_css()
    st.title("📊 Statistics")

    settings = load_settings()
    time_range, title = range_selector("stats", settings, default="Week")

    choice = st.segmented_control(
        "Group by", list(FILTER_TYPES), default="Activities", key="stats_filter"
    )
    filter_type = FILTER_TYPES[choice or "Activities"]
    filter_name = filter_type.value

    show_untracked = st.toggle(
        "Show untracked time", value=settings.show_untracked, key="stats_untracked"
    )

    statistics, records = statistics_for_range(time_range, filter_type, add_untracked=show_untracked)
    statistics = [s for s in statistics if s.duration > 0]
    if not statistics:
        st.info("Nothing tracked in this range.")
        return

    entities = entities_for_filter(filter_name)
    _summary(records, time_range, settings)

    col_chart, col_list = st.columns([3, 2])
    with col_chart:
        _donut(statistics, entities, settings)
    with col_list:
        _ranked_list(statistics, entities, settings)

    _daily_chart(records, time_range, entities, filter_type, settings)
    _table(statistics, entities, settings)
    _detail(records, time_range, entities, filter_type, settings)


def _summary_values(
    records: list[Record], time_range: Range, show_seconds: bool = True
) -> tuple[int, int]:
    """Tracked totals come from unique records, independent of grouping."""
    tracked = [record for record in records if record.type_id != UNTRACKED_ITEM_ID]
    return (
        duration_in_range(tracked, time_range, show_seconds),
        len(records_in_range(tracked, time_range)),
    )


def _summary(records: list[Record], time_range: Range, settings: Settings) -> None:
    total, count = _summary_values(records, time_range, settings.show_seconds)
    days = max(len(split_into_days(time_range, settings.start_of_day_shift)), 1)

    col_total, col_count, col_avg = st.columns(3)
    col_total.metric("Total tracked", duration_text(total, settings))
    col_count.metric("Records", count)
    col_avg.metric("Average per day", format_duration(total // days, show_seconds=False))


def _donut(statistics, entities: dict[int, Entity], settings: Settings) -> None:
    """Share of time per group. A donut keeps the total readable in the middle."""
    known = [s for s in statistics if s.id in entities]
    labels = [entities[s.id].name for s in known]
    values = [s.duration / HOUR_MS for s in known]
    colors = [entities[s.id].color for s in known]
    total = sum(s.duration for s in known)

    figure = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            marker=dict(colors=colors, line=dict(color="rgba(255,255,255,0.9)", width=2)),
            hole=0.62,
            sort=False,
            direction="clockwise",
            # One decimal, like the ranked list beside it — Plotly's default
            # precision renders a sliver as "0.00825%" next to its "0.0%".
            texttemplate="%{label}<br>%{percent:.1%}",
            textposition="outside",
            hovertemplate="%{label}<br>%{customdata}<br>%{percent:.1%}<extra></extra>",
            customdata=[format_duration(s.duration, settings.show_seconds) for s in known],
        )
    )
    figure.update_traces(automargin=True)
    figure.update_layout(
        showlegend=False,
        uniformtext=dict(minsize=11, mode="hide"),
        margin=dict(t=20, b=20, l=20, r=20),
        height=360,
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        annotations=[
            dict(
                text=f"<b>{format_duration(total, show_seconds=False)}</b><br><span style='font-size:0.8em'>total</span>",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=16),
            )
        ],
    )
    st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})


def _ranked_list(statistics, entities: dict[int, Entity], settings: Settings) -> None:
    total = sum(s.duration for s in statistics) or 1
    for stat in statistics:
        entity = entities.get(stat.id)
        if entity is None:
            continue
        share = stat.duration / total * 100
        st.markdown(
            f"{chip(entity)} <b>{duration_text(stat.duration, settings)}</b>"
            f" <span style='opacity:0.6'>· {share:.1f}% · {stat.count} "
            f"record{'' if stat.count == 1 else 's'}</span>",
            unsafe_allow_html=True,
        )
        st.progress(min(share / 100, 1.0))


def _grouped_records(
    records: list[Record],
    filter_type: ChartFilterType,
) -> dict[int, list[Record]]:
    from .. import repository as repo
    from ..domain.statistics import group_by_activity, group_by_category, group_by_tag
    from ..models import UNCATEGORIZED_ITEM_ID

    if filter_type is ChartFilterType.CATEGORY:
        links: dict[int, list[int]] = {}
        for type_id, category_id in repo.get_type_category_links():
            links.setdefault(type_id, []).append(category_id)
        return group_by_category(records, links, uncategorized_id=UNCATEGORIZED_ITEM_ID)
    if filter_type is ChartFilterType.TAG:
        return group_by_tag(records, untagged_id=UNCATEGORIZED_ITEM_ID)
    return group_by_activity(records)


def _daily_chart(
    records: list[Record],
    time_range: Range,
    entities: dict[int, Entity],
    filter_type: ChartFilterType,
    settings: Settings,
) -> None:
    """Tracked hours per day, stacked by group."""
    days = split_into_days(time_range, settings.start_of_day_shift)
    if not days:
        st.caption("Pick a bounded range to see the daily breakdown.")
        return
    if len(days) > 92:
        days = days[-92:]
        st.caption("Showing the last 92 days of the range.")

    grouped = _grouped_records(records, filter_type)
    day_labels = [_day_label(day, settings) for day in days]

    figure = go.Figure()
    for group_id, group_records in sorted(
        grouped.items(), key=lambda item: sum(r.duration for r in item[1]), reverse=True
    ):
        entity = entities.get(group_id)
        if entity is None:
            continue
        values = [
            sum(clamp_to_range(r, day).duration for r in records_in_range(group_records, day)) / HOUR_MS
            for day in days
        ]
        if not any(values):
            continue
        figure.add_bar(
            name=entity.name,
            x=day_labels,
            y=values,
            marker=dict(color=entity.color, line=dict(width=0)),
            hovertemplate="%{x}<br>" + entity.name + ": %{y:.2f} h<extra></extra>",
        )

    figure.update_layout(
        barmode="stack",
        bargap=0.25,
        height=360,
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        yaxis=dict(title="hours", gridcolor=GRID_COLOR, zerolinecolor=GRID_COLOR),
        xaxis=dict(showgrid=False),
    )
    st.subheader("Per day")
    st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})


def _table(statistics, entities: dict[int, Entity], settings: Settings) -> None:
    total = sum(s.duration for s in statistics) or 1
    frame = pd.DataFrame(
        [
            {
                "": entities[s.id].icon,
                "Name": entities[s.id].name,
                "Duration": duration_text(s.duration, settings),
                "Hours": round(s.duration / HOUR_MS, 2),
                "Share %": round(s.duration / total * 100, 1),
                "Records": s.count,
            }
            for s in statistics
            if s.id in entities
        ]
    )
    with st.expander("Table view"):
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.download_button(
            "Download CSV",
            frame.to_csv(index=False).encode(),
            file_name="statistics.csv",
            mime="text/csv",
        )


def _detail(
    records: list[Record],
    time_range: Range,
    entities: dict[int, Entity],
    filter_type: ChartFilterType,
    settings: Settings,
) -> None:
    """The app's statistics detail screen for a single activity/category/tag."""
    grouped = _grouped_records(records, filter_type)
    options = [group_id for group_id in grouped if group_id in entities]
    if not options:
        return

    st.subheader("Detail")
    selected = st.selectbox(
        "Show details for",
        options,
        format_func=lambda i: f"{entities[i].icon} {entities[i].name}",
        key="stats_detail",
    )
    group_records = grouped[selected]
    days = split_into_days(time_range, settings.start_of_day_shift)

    durations = [
        sum(clamp_to_range(r, day).duration for r in records_in_range(group_records, day))
        for day in days
    ] or [sum(r.duration for r in group_records)]
    total = sum(durations)
    tracked_days = [d for d in durations if d > 0]

    col_total, col_avg, col_best = st.columns(3)
    col_total.metric("Total", duration_text(total, settings))
    col_avg.metric(
        "Average per tracked day",
        format_duration(total // len(tracked_days), show_seconds=False) if tracked_days else "–",
    )
    col_best.metric("Longest day", format_duration(max(durations, default=0), show_seconds=False))

    if len(days) > 1:
        entity = entities[selected]
        figure = go.Figure(
            go.Bar(
                x=[_day_label(day, settings) for day in days],
                y=[d / HOUR_MS for d in durations],
                marker=dict(color=entity.color),
                hovertemplate="%{x}<br>%{y:.2f} h<extra></extra>",
            )
        )
        figure.update_layout(
            height=260,
            margin=dict(t=10, b=10, l=10, r=10),
            paper_bgcolor=SURFACE,
            plot_bgcolor=SURFACE,
            yaxis=dict(title="hours", gridcolor=GRID_COLOR, zerolinecolor=GRID_COLOR),
            xaxis=dict(showgrid=False),
            showlegend=False,
        )
        st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})

    _hourly_chart(group_records, entities[selected], time_range)


def _day_label(day: Range, settings: Settings) -> str:
    logical_start = shift_timestamp(day.time_started, -settings.start_of_day_shift)
    return to_datetime(logical_start).strftime("%d %b")


def _hourly_durations(records: list[Record], time_range: Range) -> list[float]:
    """Hours by time of day, limited to the selected statistics range."""
    if not time_range.is_undefined:
        records = [
            Record(
                type_id=record.type_id,
                time_started=clamped.time_started,
                time_ended=clamped.time_ended,
            )
            for record in records_in_range(records, time_range)
            if (clamped := clamp_to_range(record, time_range)).duration > 0
        ]

    hours = [0.0] * 24
    for record in records:
        cursor = record.time_started
        while cursor < record.time_ended:
            moment = to_datetime(cursor)
            hour_end = min(
                record.time_ended,
                int(moment.replace(minute=0, second=0, microsecond=0).timestamp() * 1000)
                + HOUR_MS,
            )
            hours[moment.hour] += (hour_end - cursor) / HOUR_MS
            cursor = hour_end
    return hours


def _hourly_chart(records: list[Record], entity: Entity, time_range: Range) -> None:
    """When during the day this activity usually happens."""
    hours = _hourly_durations(records, time_range)

    if not any(hours):
        return

    figure = go.Figure(
        go.Bar(
            x=[f"{h:02d}" for h in range(24)],
            y=hours,
            marker=dict(color=entity.color),
            hovertemplate="%{x}:00<br>%{y:.2f} h<extra></extra>",
        )
    )
    figure.update_layout(
        height=220,
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        yaxis=dict(title="hours", gridcolor=GRID_COLOR, zerolinecolor=GRID_COLOR),
        xaxis=dict(title="hour of day", showgrid=False),
        showlegend=False,
    )
    st.caption("Time of day")
    st.plotly_chart(figure, use_container_width=True, config={"displayModeBar": False})
