"""Emoji stand-ins for the Android app's vector icon set."""

from __future__ import annotations

ICONS: dict[str, list[str]] = {
    "Activity": ["🏃", "🚴", "🏊", "🧘", "⚽", "🏋️", "🥾", "⛷️", "🤸", "🧗"],
    "Work": ["💼", "💻", "📊", "📞", "✉️", "📝", "🖥️", "⌨️", "📈", "🗂️"],
    "Study": ["📚", "🎓", "🔬", "🧮", "🗒️", "✏️", "🌐", "🧪", "📐", "🔭"],
    "Home": ["🏠", "🧹", "🍳", "🧺", "🛒", "🔧", "🪴", "🐕", "🛏️", "🚿"],
    "Leisure": ["🎮", "🎬", "🎵", "📺", "🎨", "🎸", "🍿", "🎲", "📖", "🎤"],
    "Social": ["👥", "🍻", "☕", "🎉", "💬", "📱", "🤝", "🍽️", "💞", "🎁"],
    "Health": ["😴", "🩺", "💊", "🦷", "🧠", "🚭", "🥗", "💧", "🧴", "🩹"],
    "Travel": ["✈️", "🚗", "🚆", "🚌", "🚶", "🗺️", "🏖️", "🏕️", "🧳", "⛽"],
    "Other": ["⭐", "❓", "⏰", "🔔", "📌", "🔥", "💡", "🎯", "🧩", "🗓️"],
}

DEFAULT_ICON = "⭐"
UNTRACKED_ICON = "❓"

ALL_ICONS: list[str] = [icon for group in ICONS.values() for icon in group]
