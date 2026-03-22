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
