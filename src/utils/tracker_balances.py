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


def custom_group_name_error(
    name: str,
    existing_group_names: list[str],
    account_names: list[str],
) -> str | None:
    """Reject a blank name, a case-insensitive duplicate, or an account's name."""
    cleaned = name.strip()
    if not cleaned:
        return "Enter a group name."
    key = cleaned.casefold()
    if any(existing.casefold() == key for existing in existing_group_names):
        return f"A group named '{cleaned}' already exists."
    if any(account.casefold() == key for account in account_names):
        return "That name matches an account. Choose a different group name."
    return None


def normalize_custom_groups(groups: list[dict], accounts: list[dict]) -> list[dict]:
    """Keep session groups keyed by account id, limited to accounts that still exist.

    Accepts ``{"name", "account_ids"}`` and legacy ``{"name", "accounts": [names]}``.
    Member order follows ``accounts``. Deleted ids are dropped. A group with no
    remaining accounts is kept so it can be removed in the UI.
    """
    name_to_id: dict[str, str] = {}
    for account in accounts:
        name_to_id.setdefault(account["name"], str(account["id"]))

    normalized = []
    for group in groups:
        raw_ids = group.get("account_ids")
        if raw_ids is None:
            raw_ids = [
                name_to_id[member]
                for member in group.get("accounts", [])
                if member in name_to_id
            ]
        wanted = {str(account_id) for account_id in raw_ids}
        live_ids = []
        seen = set()
        for account in accounts:
            account_id = str(account["id"])
            if account_id in wanted and account_id not in seen:
                seen.add(account_id)
                live_ids.append(account_id)
        normalized.append({"name": group["name"], "account_ids": live_ids})
    return normalized


def custom_group_members(
    groups: list[dict],
    accounts: list[dict],
) -> list[tuple[str, list[str]]]:
    """Current account names for each group, in account-list order."""
    id_to_name = {str(account["id"]): account["name"] for account in accounts}
    members = []
    for group in groups:
        names = []
        for account_id in group.get("account_ids", []):
            name = id_to_name.get(str(account_id))
            if name is not None and name not in names:
                names.append(name)
        members.append((group["name"], names))
    return members
