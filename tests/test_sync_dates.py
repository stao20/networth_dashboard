from datetime import date

from utils.sync.dates import previous_month_end


def test_previous_month_end_from_first():
    assert previous_month_end(date(2026, 10, 1)) == date(2026, 9, 30)


def test_previous_month_end_january():
    assert previous_month_end(date(2026, 1, 15)) == date(2025, 12, 31)
