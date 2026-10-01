"""Pure helpers for net worth tracker DataFrames (no Streamlit / Supabase imports)."""

from datetime import date

import pandas as pd


def latest_balances_from_account_df(
    df: pd.DataFrame,
    group_by: str = "category",
    as_of_date: date | None = None,
) -> list[dict]:
    """Balances for accounts that have an entry on exactly as_of_date.

    Only accounts with a value recorded on the chosen date are included — inactive accounts
    (no entry on that date) are excluded. If as_of_date is None, uses the latest date in the data.

    group_by: \"category\" -> [{\"name\", \"value\"}]; \"account\" -> [{\"name\", \"category_name\", \"value\"}].
    """
    if df.empty:
        return []

    df = df.copy()
    if as_of_date is None:
        as_of_date = df["date"].max()
    df = df[df["date"] == as_of_date]
    if df.empty:
        return []

    latest = df.drop_duplicates(subset=["account_name"], keep="last")

    if group_by == "account":
        rows = []
        for _, row in latest.sort_values("account_name").iterrows():
            val = float(row["value"])
            if pd.isna(val):
                continue
            rows.append(
                {
                    "name": row["account_name"],
                    "category_name": row["category_name"],
                    "value": val,
                }
            )
        return rows

    by_cat = latest.groupby("category_name")["value"].sum()
    rows = []
    for cat_name in sorted(by_cat.index):
        total = float(by_cat[cat_name])
        if pd.isna(total):
            continue
        rows.append({"name": cat_name, "value": total})
    return rows


def value_trends(
    df: pd.DataFrame,
    groups: list[tuple[str, list[str]]],
) -> list[tuple[str, pd.DataFrame]]:
    """Sum account values by date for each named group.

    Each group is ``(series_name, account_names)``. A row is included when its
    ``account_name`` is in that list. Category trends pass every account in the
    category; account trends pass a single account name. Groups with no matching
    rows are omitted. Dates that have no row are left out (no forward fill).

    Returned frames have columns ``date`` (datetime64) and ``value``, ordered by
    date. Group order is preserved.
    """
    if df.empty or not groups:
        return []

    series: list[tuple[str, pd.DataFrame]] = []
    for name, account_names in groups:
        if not account_names:
            continue
        subset = df[df["account_name"].isin(account_names)]
        if subset.empty:
            continue
        grouped = subset.groupby("date")["value"].sum().reset_index()
        grouped["date"] = pd.to_datetime(grouped["date"])
        series.append((name, grouped))
    return series
