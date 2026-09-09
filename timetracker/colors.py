"""Color palette, ported from the Android app's Material color picker.

An activity/category/tag stores an ``AppColor``: either an index into
:data:`COLORS` (``color_id``) or a custom hex string (``color_int``).
"""

from __future__ import annotations

from dataclasses import dataclass

# Material 500 shades, in the order the Android color picker shows them.
COLORS: list[str] = [
    "#F44336",  # red
    "#E91E63",  # pink
    "#9C27B0",  # purple
    "#673AB7",  # deep purple
    "#3F51B5",  # indigo
    "#2196F3",  # blue
    "#03A9F4",  # light blue
    "#00BCD4",  # cyan
    "#009688",  # teal
    "#4CAF50",  # green
    "#8BC34A",  # light green
    "#CDDC39",  # lime
    "#FFEB3B",  # yellow
    "#FFC107",  # amber
    "#FF9800",  # orange
    "#FF5722",  # deep orange
    "#795548",  # brown
    "#9E9E9E",  # grey
    "#607D8B",  # blue grey
    "#000000",  # black
]

COLOR_NAMES: list[str] = [
    "Red", "Pink", "Purple", "Deep purple", "Indigo", "Blue", "Light blue",
    "Cyan", "Teal", "Green", "Light green", "Lime", "Yellow", "Amber",
    "Orange", "Deep orange", "Brown", "Grey", "Blue grey", "Black",
]

UNTRACKED_COLOR = "#616161"


@dataclass(frozen=True)
class AppColor:
    """Either a palette index (``color_int`` empty) or a custom hex color."""

    color_id: int = 0
    color_int: str = ""

    @property
    def hex(self) -> str:
        if self.color_int:
            return self.color_int
        return COLORS[self.color_id % len(COLORS)]

    @staticmethod
    def from_hex(value: str) -> "AppColor":
        """Store as a palette id when the hex matches the palette exactly."""
        value = value.upper()
        if value in COLORS:
            return AppColor(color_id=COLORS.index(value), color_int="")
        return AppColor(color_id=0, color_int=value)


def text_color_for(background_hex: str) -> str:
    """Black or white foreground, whichever stays readable on the background."""
    digits = background_hex.lstrip("#")
    r, g, b = (int(digits[i:i + 2], 16) for i in (0, 2, 4))
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.6 else "#FFFFFF"
