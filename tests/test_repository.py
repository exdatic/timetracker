"""Tests for storage and the service layer, against a temporary database."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from timetracker import repository as repo
from timetracker import service
from timetracker.colors import AppColor
from timetracker.domain.duration import HOUR_MS, MINUTE_MS
from timetracker.domain.ranges import RangeLength
from timetracker.domain.statistics import ChartFilterType
from timetracker.models import (
    Category,
    Goal,
    GoalIdType,
    GoalRange,
    GoalType,
    Range,
    Record,
    RecordTag,
    RecordType,
    now_ms,
)


@pytest.fixture(autouse=True)
def temp_database(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMETRACKER_DB", str(tmp_path / "test.db"))
    yield


@pytest.fixture
def activity() -> RecordType:
    type_id = repo.save_record_type(
        RecordType(name="Work", icon="💼", color=AppColor(color_id=4))
    )
    saved = repo.get_record_type(type_id)
    assert saved is not None
    return saved


def test_activity_round_trip(activity):
    assert activity.name == "Work"
    assert activity.color.hex == "#3F51B5"

    activity.name = "Deep work"
    repo.save_record_type(activity)
    assert [t.name for t in repo.get_record_types()] == ["Deep work"]


def test_hidden_activities_can_be_filtered_out(activity):
    activity.hidden = True
    repo.save_record_type(activity)
    assert repo.get_record_types(include_hidden=False) == []
    assert len(repo.get_record_types()) == 1


def test_record_keeps_its_tags(activity):
    tag_id = repo.save_tag(RecordTag(name="Focused"))
    record_id = repo.save_record(
        Record(type_id=activity.id, time_started=1_000, time_ended=2_000, tag_ids=[tag_id])
    )

    stored = repo.get_record(record_id)
    assert stored is not None
    assert stored.tag_ids == [tag_id]

    stored.tag_ids = []
    repo.save_record(stored)
    assert repo.get_record(record_id).tag_ids == []


def test_records_are_queried_by_overlap(activity):
    repo.save_record(Record(type_id=activity.id, time_started=1_000, time_ended=5_000))
    assert len(repo.get_records(Range(4_000, 9_000))) == 1
    assert repo.get_records(Range(5_000, 9_000)) == []


def test_deleting_an_activity_removes_its_records_and_goals(activity):
    repo.save_record(Record(type_id=activity.id, time_started=1_000, time_ended=2_000))
    repo.save_goal(Goal(id_type=GoalIdType.TYPE, id_value=activity.id, value=HOUR_MS))

    repo.delete_record_type(activity.id)

    assert repo.get_records() == []
    assert repo.get_goals() == []
    assert repo.get_record_types() == []


def test_start_and_stop_creates_a_record(activity):
    started = now_ms() - 30 * MINUTE_MS
    repo.start_running_record(activity.id, time_started=started, comment="focus")

    assert len(repo.get_running_records()) == 1

    record_id = repo.stop_running_record(activity.id)
    assert repo.get_running_records() == []

    record = repo.get_record(record_id)
    assert record is not None
    assert record.comment == "focus"
    assert record.duration == pytest.approx(30 * MINUTE_MS, abs=2_000)


def test_concurrent_stops_create_only_one_record(activity, monkeypatch):
    repo.start_running_record(activity.id, time_started=now_ms() - MINUTE_MS)

    # Make the old read/save/delete implementation deterministically expose
    # its race. The transactional implementation does not use this helper.
    original_get = repo.get_running_record
    both_read = threading.Barrier(2)

    def synchronized_get(type_id):
        running = original_get(type_id)
        both_read.wait(timeout=5)
        return running

    monkeypatch.setattr(repo, "get_running_record", synchronized_get)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(repo.stop_running_record, [activity.id, activity.id]))

    assert sum(result is not None for result in results) == 1
    assert len(repo.get_records()) == 1
    assert repo.get_running_records() == []


def test_starting_without_multitasking_stops_the_other_activity(activity):
    other = repo.save_record_type(RecordType(name="Gaming"))
    repo.set_pref("allow_multitasking", False)

    service.start_activity(activity.id)
    service.start_activity(other)

    running = repo.get_running_records()
    assert [r.id for r in running] == [other]
    assert len(repo.get_records()) == 1


def test_multitasking_keeps_both_running(activity):
    other = repo.save_record_type(RecordType(name="Music"))
    service.start_activity(activity.id)
    service.start_activity(other)
    assert len(repo.get_running_records()) == 2


def test_selectable_tags_are_general_plus_assigned(activity):
    other = repo.save_record_type(RecordType(name="Sport"))
    general = repo.save_tag(RecordTag(name="General"))
    specific = repo.save_tag(RecordTag(name="Only work"))
    repo.set_types_of_tag(specific, [activity.id])

    assert {t.id for t in repo.get_selectable_tags(activity.id)} == {general, specific}
    assert {t.id for t in repo.get_selectable_tags(other)} == {general}


def test_statistics_group_by_category(activity):
    category_id = repo.save_category(Category(name="Productive"))
    repo.set_categories_of_type(activity.id, [category_id])

    day = service.current_range(RangeLength.DAY)
    repo.save_record(
        Record(
            type_id=activity.id,
            time_started=day.time_started + 9 * HOUR_MS,
            time_ended=day.time_started + 11 * HOUR_MS,
        )
    )

    statistics, _ = service.statistics_for_range(day, ChartFilterType.CATEGORY)
    assert [(s.id, s.duration) for s in statistics] == [(category_id, 2 * HOUR_MS)]


def test_statistics_include_untracked_when_asked(activity):
    day = service.current_range(RangeLength.DAY)
    start = day.time_started
    repo.save_record(Record(type_id=activity.id, time_started=start, time_ended=start + HOUR_MS))

    without, _ = service.statistics_for_range(day, add_untracked=False)
    with_untracked, _ = service.statistics_for_range(day, add_untracked=True)

    assert len(without) == 1
    assert any(s.id == -1 for s in with_untracked)


@pytest.mark.parametrize("filter_type", [ChartFilterType.CATEGORY, ChartFilterType.TAG])
def test_untracked_statistics_stay_separate_from_unclassified_records(
    activity, monkeypatch, filter_type
):
    day = service.current_range(RangeLength.DAY)
    repo.save_record(
        Record(
            type_id=activity.id,
            time_started=day.time_started,
            time_ended=day.time_started + HOUR_MS,
        )
    )
    monkeypatch.setattr(service, "now_ms", lambda: day.time_started + 3 * HOUR_MS)

    statistics, _ = service.statistics_for_range(day, filter_type, add_untracked=True)

    assert {item.id for item in statistics} == {-2, -1}


def test_goal_progress_for_a_category_covers_all_its_activities(activity):
    other = repo.save_record_type(RecordType(name="Learning"))
    category_id = repo.save_category(Category(name="Productive"))
    repo.set_categories_of_type(activity.id, [category_id])
    repo.set_categories_of_type(other, [category_id])

    day = service.current_range(RangeLength.DAY)
    for type_id in (activity.id, other):
        repo.save_record(
            Record(
                type_id=type_id,
                time_started=day.time_started + HOUR_MS,
                time_ended=day.time_started + 2 * HOUR_MS,
            )
        )

    goal = Goal(
        id_type=GoalIdType.CATEGORY,
        id_value=category_id,
        range=GoalRange.DAILY,
        type=GoalType.DURATION,
        value=4 * HOUR_MS,
    )
    goal.id = repo.save_goal(goal)

    progress = service.progress_for_goal(goal)
    assert progress.current == 2 * HOUR_MS
    assert progress.percent == 50


def test_preferences_have_defaults_and_persist():
    assert repo.get_bool_pref("show_seconds") is True
    repo.set_pref("show_seconds", False)
    assert repo.get_bool_pref("show_seconds") is False


def test_backup_round_trip(activity):
    from timetracker.ui.settings import export_backup, import_backup

    category_id = repo.save_category(Category(name="Productive"))
    repo.set_categories_of_type(activity.id, [category_id])
    tag_id = repo.save_tag(RecordTag(name="Focused"))
    repo.save_record(
        Record(type_id=activity.id, time_started=1_000, time_ended=2_000, tag_ids=[tag_id])
    )
    repo.save_goal(Goal(id_type=GoalIdType.TYPE, id_value=activity.id, value=HOUR_MS))
    repo.set_pref("show_seconds", False)

    backup = export_backup()
    import_backup(backup)

    assert [t.name for t in repo.get_record_types()] == ["Work"]
    assert [c.name for c in repo.get_categories()] == ["Productive"]
    assert repo.get_categories_of_type(activity.id) == [category_id]
    assert len(repo.get_records()) == 1
    assert repo.get_records()[0].tag_ids == [tag_id]
    assert len(repo.get_goals()) == 1
    assert repo.get_bool_pref("show_seconds") is False


def test_invalid_backup_does_not_modify_existing_database(activity):
    from timetracker.ui.settings import export_backup, import_backup

    backup = export_backup()
    backup["records"] = [
        {
            "id": 1,
            "type_id": activity.id,
            "time_started": 2_000,
            "time_ended": 1_000,
            "tag_ids": [],
        }
    ]

    with pytest.raises(ValueError, match="must end after"):
        import_backup(backup)

    assert [item.name for item in repo.get_record_types()] == ["Work"]


def test_failed_backup_write_does_not_modify_existing_database(activity, monkeypatch):
    from timetracker.ui.settings import export_backup, import_backup

    backup = export_backup()
    original = repo.save_record_type

    def fail_after_write(record_type):
        original(record_type)
        raise RuntimeError("simulated disk failure")

    monkeypatch.setattr(repo, "save_record_type", fail_after_write)
    with pytest.raises(RuntimeError, match="simulated disk failure"):
        import_backup(backup)

    assert repo.get_record_type(activity.id).name == "Work"


def test_backup_version_is_validated_before_restore(activity):
    from timetracker.ui.settings import export_backup, import_backup

    backup = export_backup()
    backup["version"] = 999

    with pytest.raises(ValueError, match="Unsupported backup version"):
        import_backup(backup)

    assert repo.get_record_type(activity.id) is not None


def test_seed_creates_a_usable_database():
    from timetracker.seed import database_is_empty, seed_demo_data

    assert database_is_empty()
    seed_demo_data(days=10)

    assert not database_is_empty()
    assert len(repo.get_record_types()) == 10
    assert repo.get_records()
    assert repo.get_goals()


def test_database_with_only_categories_is_not_empty():
    from timetracker.seed import database_is_empty

    repo.save_category(Category(name="Existing"))

    assert not database_is_empty()
