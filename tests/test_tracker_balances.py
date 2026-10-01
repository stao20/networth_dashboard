"""Tests for net worth tracker DataFrame helpers."""

from datetime import date

import pandas as pd

from utils.tracker_balances import value_trends


def _account_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": date(2026, 1, 1), "account_name": "ISA", "category_name": "Investments", "value": 100.0},
            {"date": date(2026, 1, 1), "account_name": "GIA", "category_name": "Investments", "value": 40.0},
            {"date": date(2026, 2, 1), "account_name": "ISA", "category_name": "Investments", "value": 110.0},
            {"date": date(2026, 2, 1), "account_name": "Current", "category_name": "Cash", "value": 25.0},
        ]
    )


def test_value_trends_sums_accounts_within_each_category():
    series = value_trends(
        _account_df(),
        [
            ("Investments", ["ISA", "GIA"]),
            ("Cash", ["Current"]),
        ],
    )

    assert [name for name, _ in series] == ["Investments", "Cash"]
    investments = series[0][1]
    assert list(investments["value"]) == [140.0, 110.0]
    assert list(pd.to_datetime(investments["date"])) == list(
        pd.to_datetime([date(2026, 1, 1), date(2026, 2, 1)])
    )
    cash = series[1][1]
    assert list(cash["value"]) == [25.0]
    # Missing dates stay missing — no forward fill.
    assert len(cash) == 1


def test_value_trends_keeps_one_series_per_account():
    series = value_trends(
        _account_df(),
        [
            ("ISA", ["ISA"]),
            ("GIA", ["GIA"]),
            ("Current", ["Current"]),
        ],
    )

    assert [name for name, _ in series] == ["ISA", "GIA", "Current"]
    by_name = {name: frame for name, frame in series}
    assert list(by_name["ISA"]["value"]) == [100.0, 110.0]
    assert list(by_name["GIA"]["value"]) == [40.0]
    assert list(by_name["Current"]["value"]) == [25.0]


def test_value_trends_omits_empty_groups_and_empty_frames():
    assert value_trends(pd.DataFrame(), [("ISA", ["ISA"])]) == []
    series = value_trends(_account_df(), [("Missing", ["Nope"]), ("ISA", ["ISA"])])
    assert [name for name, _ in series] == ["ISA"]
