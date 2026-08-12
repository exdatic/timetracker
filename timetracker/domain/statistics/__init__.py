"""Statistics aggregation — a port of the app's ``StatisticsInteractor``.

Everything here is pure: it takes records and gives back numbers, so the
calculations can be tested without a database.

Split into three parts — ``filters`` selects and trims records against a
range, ``grouping`` buckets them by activity, category or tag, and
``aggregation`` turns those buckets into durations and counts. Import from
the package; the module split is an implementation detail.
"""

from .aggregation import (
    get_statistics,
    get_statistics_from_records,
    percentages,
    sum_durations,
    total_duration,
)
from .filters import ChartFilterType, clamp, overlapping
from .grouping import group_by_activity, group_by_category, group_by_tag

__all__ = [
    "ChartFilterType",
    "clamp",
    "get_statistics",
    "get_statistics_from_records",
    "group_by_activity",
    "group_by_category",
    "group_by_tag",
    "overlapping",
    "percentages",
    "sum_durations",
    "total_duration",
]
