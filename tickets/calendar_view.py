"""Calendar helpers for the ticket board."""

from __future__ import annotations

import calendar
from datetime import date, timedelta


def parse_iso_date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def build_calendar_days(
    year: int,
    month: int,
    counts_by_date: dict[str, dict[str, int]],
) -> list[dict]:
    """Build a Mon–Sun calendar grid for the month."""
    first = date(year, month, 1)
    # Monday = 0
    start = first - timedelta(days=first.weekday())
    days: list[dict] = []
    cursor = start
    for _ in range(42):
        key = cursor.isoformat()
        stats = counts_by_date.get(key, {})
        total = int(stats.get("total", 0))
        days.append(
            {
                "date": key,
                "day": cursor.day,
                "in_month": cursor.month == month,
                "has_tickets": total > 0,
                "total": total,
                "open": int(stats.get("open", 0)),
                "resolved": int(stats.get("resolved", 0)),
            }
        )
        cursor += timedelta(days=1)
    return days


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    month += delta
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return year, month


def month_title(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"
