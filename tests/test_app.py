"""Smoke tests that actually render every page with Streamlit's test runner."""

from __future__ import annotations

from datetime import datetime

import pytest
from streamlit.testing.v1 import AppTest

from timetracker import repository as repo
from timetracker import service
from timetracker.domain.ranges import RangeLength
from timetracker.domain.duration import HOUR_MS
from timetracker.domain.ranges import to_ms
from timetracker.models import Category, Goal, GoalIdType, Range, Record, RecordTag, RecordType
from timetracker.seed import seed_demo_data

PAGES = [
    "timetracker/ui/running.py",
    "timetracker/ui/records.py",
    "timetracker/ui/statistics.py",
    "timetracker/ui/goals.py",
    "timetracker/ui/activities.py",
    "timetracker/ui/settings.py",
]

RUNNER = """
import sys
sys.path.insert(0, {root!r})
from timetracker.ui import {module} as page
page.render()
"""


@pytest.fixture(autouse=True)
def temp_database(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMETRACKER_DB", str(tmp_path / "test.db"))
    yield


def run_page(module: str) -> AppTest:
    root = str(__import__("pathlib").Path(__file__).resolve().parent.parent)
    app = AppTest.from_string(RUNNER.format(root=root, module=module), default_timeout=30)
    app.run()
    return app


@pytest.mark.parametrize("module", ["running", "records", "statistics", "goals", "activities", "settings"])
def test_page_renders_on_an_empty_database(module):
    app = run_page(module)
    assert not app.exception


@pytest.mark.parametrize("module", ["running", "records", "statistics", "goals", "activities", "settings"])
def test_page_renders_with_demo_data(module):
    seed_demo_data(days=14)
    app = run_page(module)
    assert not app.exception


def test_starting_an_activity_from_the_timers_page():
    seed_demo_data(days=2)
    work = next(t for t in repo.get_record_types() if t.name == "Work")

    app = run_page("running")
    app.button(key=f"grid_start_{work.id}").click().run()

    assert [r.id for r in repo.get_running_records()] == [work.id]


def test_stopping_an_activity_writes_a_record():
    seed_demo_data(days=2)
    work = next(t for t in repo.get_record_types() if t.name == "Work")
    before = len(repo.get_records())
    repo.start_running_record(work.id)

    app = run_page("running")
    app.button(key=f"stop_{work.id}").click().run()

    assert repo.get_running_records() == []
    assert len(repo.get_records()) == before + 1


def test_record_filters_do_not_turn_hidden_activity_time_into_untracked():
    from timetracker.ui.records import _with_untracked

    first = repo.save_record_type(RecordType(name="First"))
    second = repo.save_record_type(RecordType(name="Second"))
    start = to_ms(datetime(2026, 1, 1))
    first_record = Record(type_id=first, time_started=start, time_ended=start + HOUR_MS)
    second_record = Record(
        type_id=second,
        time_started=start + HOUR_MS,
        time_ended=start + 2 * HOUR_MS,
    )
    repo.save_record(first_record)
    repo.save_record(second_record)

    result = _with_untracked(
        Range(start, start + 2 * HOUR_MS),
        displayed_records=[first_record],
        coverage_records=[first_record, second_record],
    )

    assert result == [first_record]


def test_hourly_statistics_are_clamped_to_selected_range():
    from timetracker.ui.statistics import _hourly_durations

    start = to_ms(datetime(2026, 1, 1))
    selected = Range(start, start + 24 * HOUR_MS)
    crossing = Record(
        type_id=1,
        time_started=start - HOUR_MS,
        time_ended=start + HOUR_MS,
    )

    hours = _hourly_durations([crossing], selected)

    assert sum(hours) == 1.0
    assert hours[0] == 1.0


def test_imported_icons_are_escaped_in_html_cards():
    from timetracker.ui.common import Entity, card

    rendered = card(Entity(1, "Safe", "<img src=x onerror=alert(1)>", "#000000"))

    assert "<img" not in rendered
    assert "&lt;img" in rendered


def test_a_record_is_not_saved_when_its_date_is_cleared():
    seed_demo_data(days=2)
    before = len(repo.get_records())

    app = run_page("records")
    app.date_input(key="add_start_date").set_value(None).run()
    app.button(key="add_record").click().run()

    assert not app.exception
    assert len(repo.get_records()) == before
    assert any("valid date and time" in str(e.value) for e in app.error)


def test_editing_a_record_preserves_archived_and_reassigned_tags():
    activity = repo.save_record_type(RecordType(name="Work"))
    other = repo.save_record_type(RecordType(name="Sport"))
    archived = repo.save_tag(RecordTag(name="Old", archived=True))
    reassigned = repo.save_tag(RecordTag(name="Elsewhere"))
    repo.set_types_of_tag(reassigned, [other])

    # The records page opens on today, so the record has to be there.
    today = service.current_range(RangeLength.DAY)
    start = today.time_started + 9 * HOUR_MS
    record_id = repo.save_record(
        Record(
            type_id=activity,
            time_started=start,
            time_ended=start + HOUR_MS,
            tag_ids=[archived, reassigned],
        )
    )
    # Neither tag is offered for this activity any more.
    assert repo.get_selectable_tags(activity) == []

    app = run_page("records")
    app.text_input(key=f"edit_comment_{record_id}").set_value("edited").run()
    app.button(key=f"edit_save_{record_id}").click().run()

    assert not app.exception
    stored = repo.get_record(record_id)
    assert stored.comment == "edited"
    assert sorted(stored.tag_ids) == sorted([archived, reassigned])


def test_records_summary_excludes_displayed_untracked_gaps():
    from timetracker.models import UNTRACKED_ITEM_ID
    from timetracker.ui.records import _summary_values

    start = to_ms(datetime(2026, 1, 1))
    time_range = Range(start, start + 24 * HOUR_MS)
    tracked = Record(type_id=1, time_started=start, time_ended=start + HOUR_MS)
    gap = Record(
        type_id=UNTRACKED_ITEM_ID,
        time_started=start + HOUR_MS,
        time_ended=start + 24 * HOUR_MS,
    )

    total, count = _summary_values([tracked, gap], time_range)

    assert total == HOUR_MS
    assert count == 1


def test_statistics_summary_excludes_untracked_and_uses_unique_records():
    from timetracker.models import UNTRACKED_ITEM_ID
    from timetracker.ui.statistics import _summary_values

    start = to_ms(datetime(2026, 1, 1))
    time_range = Range(start, start + 24 * HOUR_MS)
    tracked = Record(type_id=1, time_started=start, time_ended=start + HOUR_MS)
    gap = Record(
        type_id=UNTRACKED_ITEM_ID,
        time_started=start + HOUR_MS,
        time_ended=start + 24 * HOUR_MS,
    )

    total, count = _summary_values([tracked, gap], time_range)

    assert total == HOUR_MS
    assert count == 1


def test_statistics_day_label_uses_the_logical_date():
    from timetracker.domain.ranges import split_into_days
    from timetracker.ui.statistics import _day_label

    shift = -4 * HOUR_MS
    boundary = to_ms(datetime(2026, 3, 10, 20))
    settings = service.Settings(start_of_day_shift=shift)

    day = split_into_days(Range(boundary, boundary + 24 * HOUR_MS), shift)[0]

    assert _day_label(day, settings) == "11 Mar"


def test_shifted_day_header_uses_the_logical_date():
    from timetracker.ui.common import format_day

    shift = -4 * HOUR_MS
    # 01:00 on 11 March belongs to the 10 March tracking day.
    boundary = to_ms(datetime(2026, 3, 10, 20))

    assert format_day(boundary, shift) == "Wed, 11 Mar 2026"
    assert format_day(boundary, 0) == "Tue, 10 Mar 2026"


def test_demo_data_button_is_disabled_when_database_is_not_empty():
    def demo_button(app):
        return next(b for b in app.button if b.label == "Load demo data")

    assert not demo_button(run_page("settings")).disabled

    seed_demo_data(days=2)
    assert demo_button(run_page("settings")).disabled


def test_editing_an_archived_tag_goal_preserves_its_target():
    repo.save_record_type(RecordType(name="Work"))
    archived = repo.save_tag(RecordTag(name="Archived", archived=True))
    repo.save_tag(RecordTag(name="Active"))
    goal = Goal(id_type=GoalIdType.TAG, id_value=archived, value=HOUR_MS)
    goal.id = repo.save_goal(goal)

    app = run_page("goals")
    app.button(key=f"goal_{goal.id}_save").click().run()

    assert not app.exception
    assert repo.get_goals()[0].id_value == archived


def test_duplicate_category_names_are_filtered_by_id():
    first = repo.save_record_type(RecordType(name="First"))
    second = repo.save_record_type(RecordType(name="Second"))
    first_category = repo.save_category(Category(name="Same"))
    second_category = repo.save_category(Category(name="Same"))
    repo.set_categories_of_type(first, [first_category])
    repo.set_categories_of_type(second, [second_category])

    app = run_page("running")
    app.get("button_group")[0].set_value(second_category).run()
    cards = "\n".join(markdown.value for markdown in app.markdown)

    assert not app.exception
    assert ">Second<br>" in cards
    assert ">First<br>" not in cards
