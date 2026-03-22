"""Pure helpers for net worth tracker DataFrames (no Streamlit / Supabase imports)."""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

# region agent log
_DEBUG_LOG = Path(__file__).resolve().parents[2] / "debug-ac5b05.log"


def _agent_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    try:
        line = json.dumps(
            {
                "sessionId": "ac5b05",
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(__import__("time").time() * 1000),
            }
        )
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# endregion


def normalize_tracker_date_for_compare(d: Any) -> date | None:
    """Public: normalize a tracker `date` cell for equality checks (used by simulator debug)."""
    return _to_py_date(d)


def _to_py_date(d: Any) -> date | None:
    """Normalize pandas Timestamp / datetime / str / date for comparisons."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, pd.Timestamp):
        return d.date()
    if isinstance(d, str):
        return pd.to_datetime(d).date()
    return pd.to_datetime(d).date()


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
    # region agent log
    _agent_log(
        "H1",
        "tracker_balances:latest_balances_from_account_df:entry",
        "entry",
        {
            "as_of_raw": repr(as_of_date),
            "as_of_type": type(as_of_date).__name__,
            "group_by": repr(group_by),
            "df_len": len(df),
        },
    )
    # endregion

    if df.empty:
        return []

    df = df.copy()
    df["_date_norm"] = df["date"].map(_to_py_date)

    if as_of_date is None:
        as_of_norm = df["_date_norm"].max()
        # region agent log
        _agent_log(
            "H1",
            "tracker_balances:latest_balances_from_account_df:none_as_of",
            "as_of_date was None; using max date",
            {"as_of_norm": str(as_of_norm)},
        )
        # endregion
    else:
        as_of_norm = _to_py_date(as_of_date)

    df = df[df["_date_norm"] == as_of_norm]
    df = df.drop(columns=["_date_norm"])

    # region agent log
    _agent_log(
        "H3",
        "tracker_balances:latest_balances_from_account_df:after_filter",
        "after exact date filter",
        {
            "as_of_norm": str(as_of_norm),
            "rows_after_filter": len(df),
            "unique_accounts": int(df["account_name"].nunique()) if len(df) else 0,
        },
    )
    # endregion

    if df.empty:
        return []

    latest = df.drop_duplicates(subset=["account_name"], keep="last")

    gb = (group_by or "").strip().lower()
    # region agent log
    _agent_log(
        "H4",
        "tracker_balances:latest_balances_from_account_df:branch",
        "branch",
        {"group_by_normalized": gb, "latest_len": len(latest)},
    )
    # endregion

    if gb == "account":
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
        # region agent log
        _agent_log(
            "H4",
            "tracker_balances:latest_balances_from_account_df:account_return",
            "account rows built",
            {"len_rows": len(rows)},
        )
        # endregion
        return rows

    by_cat = latest.groupby("category_name")["value"].sum()
    rows = []
    for cat_name in sorted(by_cat.index):
        total = float(by_cat[cat_name])
        if pd.isna(total):
            continue
        rows.append({"name": cat_name, "value": total})
    # region agent log
    _agent_log(
        "H4",
        "tracker_balances:latest_balances_from_account_df:category_return",
        "category rows built",
        {"len_rows": len(rows)},
    )
    # endregion
    return rows
