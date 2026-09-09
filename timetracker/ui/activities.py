"""Activities page — manage activities, categories and tags."""

from __future__ import annotations

import streamlit as st

from .. import repository as repo
from ..domain.duration import format_duration, parse_duration
from ..models import Category, RecordTag, RecordType, TagValueType
from .common import (
    card,
    category_entity,
    color_picker,
    icon_picker,
    inject_css,
    tag_entity,
    type_entity,
)


def render() -> None:
    inject_css()
    st.title("🗂️ Activities")

    activities_tab, categories_tab, tags_tab = st.tabs(["Activities", "Categories", "Tags"])
    with activities_tab:
        _activities()
    with categories_tab:
        _categories()
    with tags_tab:
        _tags()


# --------------------------------------------------------------------------- #
# Activities
# --------------------------------------------------------------------------- #


def _activities() -> None:
    with st.expander("➕ New activity"):
        _activity_form(RecordType(), key="new_type")

    types = repo.get_record_types()
    if not types:
        st.info("No activities yet.")
        return

    categories = {c.id: c for c in repo.get_categories()}
    columns = st.columns(2)
    for index, record_type in enumerate(types):
        with columns[index % 2]:
            with st.container(border=True):
                linked = [
                    categories[c].name
                    for c in repo.get_categories_of_type(record_type.id)
                    if c in categories
                ]
                subtitle = ", ".join(linked)
                if record_type.hidden:
                    subtitle = f"{subtitle} · hidden" if subtitle else "hidden"
                st.markdown(card(type_entity(record_type), subtitle), unsafe_allow_html=True)
                if record_type.note:
                    st.caption(record_type.note)
                with st.expander("Edit"):
                    _activity_form(record_type, key=f"type_{record_type.id}")


def _activity_form(record_type: RecordType, key: str) -> None:
    name = st.text_input("Name", record_type.name, key=f"{key}_name")
    col_icon, col_color = st.columns(2)
    with col_icon:
        icon = icon_picker("Icon group", record_type.icon, key=f"{key}_icon")
    with col_color:
        color = color_picker("Color", record_type.color, key=f"{key}_color")

    note = st.text_area("Note", record_type.note, key=f"{key}_note", height=68)

    default_duration_text = st.text_input(
        "Default duration",
        format_duration(record_type.default_duration, show_seconds=False)
        if record_type.default_duration
        else "",
        help="Pre-fills the length when adding a past record. Leave empty for one hour.",
        key=f"{key}_duration",
    )
    hidden = st.checkbox("Hide from the timers screen", record_type.hidden, key=f"{key}_hidden")

    categories = repo.get_categories()
    selected_categories: list[int] = []
    if categories:
        names = {c.id: c.name for c in categories}
        current = repo.get_categories_of_type(record_type.id) if record_type.id else []
        selected_categories = st.multiselect(
            "Categories",
            options=list(names),
            default=current,
            format_func=lambda i: names[i],
            key=f"{key}_categories",
        )

    col_save, col_delete = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", key=f"{key}_save"):
            if not name.strip():
                st.error("An activity needs a name.")
                return
            record_type.name = name.strip()
            record_type.icon = icon
            record_type.color = color
            record_type.note = note
            record_type.hidden = hidden
            record_type.default_duration = parse_duration(default_duration_text) or 0
            type_id = repo.save_record_type(record_type)
            repo.set_categories_of_type(type_id, selected_categories)
            st.rerun()
    with col_delete:
        if record_type.id and st.button("Delete", key=f"{key}_delete"):
            repo.delete_record_type(record_type.id)
            st.rerun()
    if record_type.id:
        st.caption("Deleting an activity also deletes its records and goals.")


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #


def _categories() -> None:
    with st.expander("➕ New category"):
        _category_form(Category(), key="new_category")

    categories = repo.get_categories()
    if not categories:
        st.info("No categories yet.")
        return

    types = repo.record_types_by_id()
    columns = st.columns(2)
    for index, category in enumerate(categories):
        with columns[index % 2]:
            with st.container(border=True):
                members = [
                    types[t].name for t in repo.get_types_of_category(category.id) if t in types
                ]
                st.markdown(
                    card(category_entity(category), ", ".join(members)), unsafe_allow_html=True
                )
                with st.expander("Edit"):
                    _category_form(category, key=f"category_{category.id}")


def _category_form(category: Category, key: str) -> None:
    name = st.text_input("Name", category.name, key=f"{key}_name")
    color = color_picker("Color", category.color, key=f"{key}_color")
    note = st.text_area("Note", category.note, key=f"{key}_note", height=68)

    types = repo.get_record_types()
    names = {t.id: f"{t.icon} {t.name}" for t in types}
    current = repo.get_types_of_category(category.id) if category.id else []
    members = st.multiselect(
        "Activities",
        options=list(names),
        default=current,
        format_func=lambda i: names[i],
        key=f"{key}_types",
    )

    col_save, col_delete = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", key=f"{key}_save"):
            if not name.strip():
                st.error("A category needs a name.")
                return
            category.name = name.strip()
            category.color = color
            category.note = note
            category_id = repo.save_category(category)
            for record_type in types:
                linked = repo.get_categories_of_type(record_type.id)
                should_link = record_type.id in members
                if should_link and category_id not in linked:
                    repo.set_categories_of_type(record_type.id, linked + [category_id])
                elif not should_link and category_id in linked:
                    repo.set_categories_of_type(
                        record_type.id, [c for c in linked if c != category_id]
                    )
            st.rerun()
    with col_delete:
        if category.id and st.button("Delete", key=f"{key}_delete"):
            repo.delete_category(category.id)
            st.rerun()


# --------------------------------------------------------------------------- #
# Tags
# --------------------------------------------------------------------------- #


def _tags() -> None:
    with st.expander("➕ New tag"):
        _tag_form(RecordTag(), key="new_tag")

    tags = repo.get_tags(include_archived=True)
    if not tags:
        st.info("No tags yet.")
        return

    types = repo.record_types_by_id()
    columns = st.columns(2)
    for index, tag in enumerate(tags):
        with columns[index % 2]:
            with st.container(border=True):
                assigned = [types[t].name for t in repo.get_types_of_tag(tag.id) if t in types]
                subtitle = ", ".join(assigned) if assigned else "general tag"
                if tag.archived:
                    subtitle += " · archived"
                st.markdown(card(tag_entity(tag, types), subtitle), unsafe_allow_html=True)
                with st.expander("Edit"):
                    _tag_form(tag, key=f"tag_{tag.id}")


def _tag_form(tag: RecordTag, key: str) -> None:
    name = st.text_input("Name", tag.name, key=f"{key}_name")
    col_icon, col_color = st.columns(2)
    with col_icon:
        icon = icon_picker("Icon group", tag.icon, key=f"{key}_icon")
    with col_color:
        color = color_picker("Color", tag.color, key=f"{key}_color")

    types = repo.get_record_types()
    names = {t.id: f"{t.icon} {t.name}" for t in types}
    current = repo.get_types_of_tag(tag.id) if tag.id else []
    assigned = st.multiselect(
        "Only for these activities",
        options=list(names),
        default=current,
        help="Leave empty to make it a general tag available everywhere.",
        format_func=lambda i: names[i],
        key=f"{key}_types",
    )

    color_source_options = [0] + list(names)
    color_source = st.selectbox(
        "Take color from activity",
        color_source_options,
        index=color_source_options.index(tag.icon_color_source)
        if tag.icon_color_source in color_source_options
        else 0,
        format_func=lambda i: "Use the tag's own color" if i == 0 else names[i],
        key=f"{key}_colorsource",
    )
    archived = st.checkbox("Archived", tag.archived, key=f"{key}_archived")

    col_save, col_delete = st.columns(2)
    with col_save:
        if st.button("Save", type="primary", key=f"{key}_save"):
            if not name.strip():
                st.error("A tag needs a name.")
                return
            tag.name = name.strip()
            tag.icon = icon
            tag.color = color
            tag.icon_color_source = color_source
            tag.archived = archived
            tag.value_type = TagValueType.NONE
            tag_id = repo.save_tag(tag)
            repo.set_types_of_tag(tag_id, assigned)
            st.rerun()
    with col_delete:
        if tag.id and st.button("Delete", key=f"{key}_delete"):
            repo.delete_tag(tag.id)
            st.rerun()
