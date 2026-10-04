from __future__ import annotations

from datetime import date, timedelta


def previous_month_end(today: date) -> date:
    first_of_month = today.replace(day=1)
    return first_of_month - timedelta(days=1)
