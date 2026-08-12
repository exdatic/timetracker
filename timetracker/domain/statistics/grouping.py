"""Bucketing records by activity, category or tag.

Each function returns ``{group_id: records}``; a record can land in more than
one bucket when it carries several categories or tags.
"""

from __future__ import annotations

from ...models import UNTRACKED_ITEM_ID, Record


def group_by_activity(records: list[Record]) -> dict[int, list[Record]]:
    grouped: dict[int, list[Record]] = {}
    for record in records:
        grouped.setdefault(record.type_id, []).append(record)
    return grouped


def group_by_category(
    records: list[Record],
    categories_of_type: dict[int, list[int]],
    uncategorized_id: int | None = None,
) -> dict[int, list[Record]]:
    grouped: dict[int, list[Record]] = {}
    for record in records:
        if record.type_id == UNTRACKED_ITEM_ID:
            grouped.setdefault(UNTRACKED_ITEM_ID, []).append(record)
            continue
        category_ids = categories_of_type.get(record.type_id, [])
        if not category_ids:
            if uncategorized_id is None:
                continue
            category_ids = [uncategorized_id]
        for category_id in category_ids:
            grouped.setdefault(category_id, []).append(record)
    return grouped


def group_by_tag(records: list[Record], untagged_id: int | None = None) -> dict[int, list[Record]]:
    grouped: dict[int, list[Record]] = {}
    for record in records:
        if record.type_id == UNTRACKED_ITEM_ID:
            grouped.setdefault(UNTRACKED_ITEM_ID, []).append(record)
            continue
        tag_ids = record.tag_ids
        if not tag_ids:
            if untagged_id is None:
                continue
            tag_ids = [untagged_id]
        for tag_id in tag_ids:
            grouped.setdefault(tag_id, []).append(record)
    return grouped
