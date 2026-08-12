"""Simple Time Tracker — a Streamlit port of the Android app.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from timetracker.ui import activities, goals, records, running, settings, statistics

st.set_page_config(
    page_title="Simple Time Tracker",
    page_icon="⏱️",
    layout="wide",
    initial_sidebar_state="expanded",
)

PAGES = [
    st.Page(running.render, title="Timers", icon="⏱️", default=True),
    st.Page(records.render, title="Records", icon="📋", url_path="records"),
    st.Page(statistics.render, title="Statistics", icon="📊", url_path="statistics"),
    st.Page(goals.render, title="Goals", icon="🎯", url_path="goals"),
    st.Page(activities.render, title="Activities", icon="🗂️", url_path="activities"),
    st.Page(settings.render, title="Settings", icon="⚙️", url_path="settings"),
]


def main() -> None:
    with st.sidebar:
        st.markdown("### ⏱️ Simple Time Tracker")
        st.caption("Track how much time you spend on all the useless activities in the world.")
        _first_run_hint()

    st.navigation(PAGES).run()


def _first_run_hint() -> None:
    """An empty database is not much to look at — offer to fill it."""
    from timetracker.seed import database_is_empty, seed_demo_data

    if not database_is_empty():
        return
    st.info("The database is empty.")
    if st.button("Load demo data", use_container_width=True):
        seed_demo_data()
        st.rerun()


main()
