"""Tests for net worth tracker DataFrame helpers."""

from utils.tracker_balances import (
    custom_group_members,
    custom_group_name_error,
    normalize_custom_groups,
)


ACCOUNTS = [
    {"id": "isa", "name": "ISA"},
    {"id": "gia", "name": "GIA"},
    {"id": "current", "name": "Current"},
]


def test_custom_group_follows_account_id_across_rename():
    groups = [{"name": "Investments mix", "account_ids": ["isa", "gia"]}]
    renamed = [
        {"id": "isa", "name": "Stocks ISA"},
        {"id": "gia", "name": "GIA"},
        {"id": "current", "name": "Current"},
    ]

    normalized = normalize_custom_groups(groups, renamed)
    members = custom_group_members(normalized, renamed)

    assert normalized == [{"name": "Investments mix", "account_ids": ["isa", "gia"]}]
    assert members == [("Investments mix", ["Stocks ISA", "GIA"])]


def test_deleted_account_drops_out_and_reused_name_does_not_join():
    groups = [{"name": "Investments mix", "account_ids": ["isa", "gia"]}]
    accounts = [
        {"id": "gia", "name": "GIA"},
        {"id": "new-isa", "name": "ISA"},
        {"id": "current", "name": "Current"},
    ]

    normalized = normalize_custom_groups(groups, accounts)
    members = custom_group_members(normalized, accounts)

    assert normalized[0]["account_ids"] == ["gia"]
    assert members == [("Investments mix", ["GIA"])]


def test_legacy_name_groups_convert_to_current_ids():
    groups = [{"name": "Cash pile", "accounts": ["Current", "Missing"]}]

    normalized = normalize_custom_groups(groups, ACCOUNTS)

    assert normalized == [{"name": "Cash pile", "account_ids": ["current"]}]


def test_custom_group_name_error_rejects_blank_case_duplicates_and_account_names():
    assert custom_group_name_error("  ", ["Mix"], ["ISA"]) == "Enter a group name."
    assert (
        custom_group_name_error("mix", ["Mix"], ["ISA"])
        == "A group named 'mix' already exists."
    )
    assert (
        custom_group_name_error("isa", [], ["ISA"])
        == "That name matches an account. Choose a different group name."
    )
    assert custom_group_name_error("Investments mix", ["Cash"], ["ISA"]) is None
