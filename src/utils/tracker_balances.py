"""Pure helpers for net worth tracker DataFrames (no Streamlit / Supabase imports)."""

from datetime import date

import pandas as pd


def latest_balances_from_account_df(
    df: pd.DataFrame,
    group_by: str = "category",
    as_of_date: date | None = None,
) -> list[dict]:
    """Compute simulator import rows from a tracker account_values DataFrame.

    For each account, uses the latest row with date <= as_of_date (inclusive). If as_of_date is
    None, uses the globally latest row per account.

    group_by: \"category\" -> [{\"name\", \"value\"}]; \"account\" -> [{\"name\", \"category_name\", \"value\"}].
    """
    if df.empty:
        return []

    df = df.copy()
    if as_of_date is not None:
        df = df[df["date"] <= as_of_date]
    if df.empty:
        return []

    latest = (
        df.sort_values("date").groupby("account_name", as_index=False).last()
    )

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
