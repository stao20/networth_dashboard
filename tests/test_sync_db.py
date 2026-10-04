from datetime import date

import pytest

from utils.db import SupabaseHandler


@pytest.fixture
def handler(fake_supabase, mocker):
    mocker.patch.object(SupabaseHandler, "__init__", lambda self: None)
    h = SupabaseHandler()
    h.supabase = fake_supabase
    return h


def test_upsert_provider_connection_trading212(handler, fake_supabase, sample_user_id):
    row = {
        "id": "conn-1",
        "user_id": sample_user_id,
        "provider": "trading212",
        "status": "active",
        "credentials_encrypted": "enc",
        "external_connection_id": "default",
        "display_name": "T212",
    }
    fake_supabase.set_table("provider_connections", [row])
    result = handler.upsert_provider_connection(
        sample_user_id, "trading212", "default", "enc", display_name="T212"
    )
    assert result["provider"] == "trading212"
    chain = fake_supabase._tables["provider_connections"].calls
    assert any(c[0] == "upsert" for c in chain)


def test_get_account_value_none_when_missing(handler, fake_supabase):
    fake_supabase.set_table("account_values", [])
    assert handler.get_account_value("acc-1", "2026-09-30") is None


def test_get_account_value_returns_float(handler, fake_supabase):
    fake_supabase.set_table(
        "account_values", [{"account_id": "acc-1", "date": "2026-09-30", "value": "123.45"}]
    )
    assert handler.get_account_value("acc-1", "2026-09-30") == 123.45


def test_delete_account_value(handler, fake_supabase):
    fake_supabase.set_table("account_values", [])
    handler.delete_account_value("acc-1", "2026-09-30")
    chain = fake_supabase._tables["account_values"].calls
    assert any(c[0] == "delete" for c in chain)
    eq_pairs = {c[1][0]: c[1][1] for c in chain if c[0] == "eq"}
    assert eq_pairs.get("account_id") == "acc-1"
    assert eq_pairs.get("date") == "2026-09-30"


def test_create_sync_run(handler, fake_supabase, sample_user_id):
    run_row = {
        "id": "run-1",
        "user_id": sample_user_id,
        "trigger": "manual",
        "as_of_date": "2026-09-30",
        "status": "running",
    }
    fake_supabase.set_table("sync_runs", [run_row])
    result = handler.create_sync_run(sample_user_id, "manual", date(2026, 9, 30))
    assert result["status"] == "running"
    assert result["id"] == "run-1"
    chain = fake_supabase._tables["sync_runs"].calls
    assert any(c[0] == "insert" for c in chain)


def test_add_sync_run_item(handler, fake_supabase):
    item_row = {
        "id": "item-1",
        "sync_run_id": "run-1",
        "provider": "trading212",
        "outcome": "written",
        "account_id": "acc-1",
        "new_value_gbp": "1000.00",
        "had_previous": False,
    }
    fake_supabase.set_table("sync_run_items", [item_row])
    result = handler.add_sync_run_item(
        "run-1",
        "trading212",
        "written",
        account_id="acc-1",
        new_value_gbp=1000.0,
        had_previous=False,
    )
    assert result["outcome"] == "written"
    chain = fake_supabase._tables["sync_run_items"].calls
    assert any(c[0] == "insert" for c in chain)


def test_list_account_mappings(handler, fake_supabase, sample_user_id):
    rows = [
        {
            "id": "map-1",
            "user_id": sample_user_id,
            "provider_connection_id": "conn-1",
            "external_account_id": "ext-1",
            "external_account_name": "Invest",
            "account_id": "acc-1",
        }
    ]
    fake_supabase.set_table("account_mappings", rows)
    out = handler.list_account_mappings(sample_user_id)
    assert len(out) == 1
    assert out[0]["external_account_name"] == "Invest"
    chain = fake_supabase._tables["account_mappings"].calls
    eq_pairs = {c[1][0]: c[1][1] for c in chain if c[0] == "eq"}
    assert eq_pairs.get("user_id") == sample_user_id


def test_mark_sync_run_undone(handler, fake_supabase):
    fake_supabase.set_table(
        "sync_runs",
        [{"id": "run-1", "undone_at": "2026-10-01T12:00:00Z", "notes": "Undo: restored=1"}],
    )
    result = handler.mark_sync_run_undone("run-1", notes="Undo: restored=1")
    assert result["notes"] == "Undo: restored=1"
    chain = fake_supabase._tables["sync_runs"].calls
    assert any(c[0] == "update" for c in chain)
    update_args = next(c[1] for c in chain if c[0] == "update")
    assert update_args[0]["undone_at"] == "now()"


def test_finalize_sync_run(handler, fake_supabase):
    fake_supabase.set_table(
        "sync_runs",
        [
            {
                "id": "run-1",
                "status": "success",
                "written_count": 2,
                "skipped_count": 1,
                "error_count": 0,
            }
        ],
    )
    result = handler.finalize_sync_run("run-1", "success", 2, 1, 0)
    assert result["status"] == "success"
    chain = fake_supabase._tables["sync_runs"].calls
    update_args = next(c[1] for c in chain if c[0] == "update")
    assert update_args[0]["finished_at"] == "now()"


def test_touch_provider_connection_synced(handler, fake_supabase):
    fake_supabase.set_table("provider_connections", [{"id": "conn-1"}])
    handler.touch_provider_connection_synced("conn-1")
    chain = fake_supabase._tables["provider_connections"].calls
    update_args = next(c[1] for c in chain if c[0] == "update")
    assert update_args[0]["last_synced_at"] == "now()"
    assert update_args[0]["status"] == "active"
    assert update_args[0]["last_error"] is None


def test_update_provider_connection_credentials_keeps_status(handler, fake_supabase):
    fake_supabase.set_table("provider_connections", [{"id": "conn-1"}])
    handler.update_provider_connection_credentials("conn-1", "new-enc")
    chain = fake_supabase._tables["provider_connections"].calls
    update_args = next(c[1] for c in chain if c[0] == "update")
    assert update_args[0]["credentials_encrypted"] == "new-enc"
    assert "status" not in update_args[0]
    eq_pairs = {c[1][0]: c[1][1] for c in chain if c[0] == "eq"}
    assert eq_pairs == {"id": "conn-1"}


@pytest.mark.parametrize(
    "method, args",
    [
        ("list_provider_connections", ("u1",)),
        ("list_account_mappings", ("u1",)),
        ("list_sync_run_items", ("run-1",)),
    ],
)
def test_list_helpers_swallow_errors_by_default_and_raise_when_strict(
    handler, fake_supabase, method, args
):
    fake_supabase.table.side_effect = RuntimeError("db down")
    assert getattr(handler, method)(*args) == []
    with pytest.raises(RuntimeError):
        getattr(handler, method)(*args, strict=True)


def test_list_user_ids_for_scheduled_sync_includes_unhealthy_connections(
    handler, fake_supabase
):
    fake_supabase.set_table(
        "provider_connections",
        [
            {"user_id": "u1", "status": "active"},
            {"user_id": "u2", "status": "needs_reauth"},
            {"user_id": "u1", "status": "error"},
        ],
    )
    assert handler.list_user_ids_for_scheduled_sync() == ["u1", "u2"]
    chain = fake_supabase._tables["provider_connections"].calls
    in_args = next(c[1] for c in chain if c[0] == "in_")
    assert in_args[0] == "status"
    assert set(in_args[1]) == {"active", "needs_reauth", "error"}


def test_list_user_ids_for_scheduled_sync_raises_on_db_error(handler, fake_supabase):
    fake_supabase.table.side_effect = RuntimeError("db down")
    with pytest.raises(RuntimeError):
        handler.list_user_ids_for_scheduled_sync()


def test_list_later_written_account_ids(handler, fake_supabase, sample_user_id):
    fake_supabase.set_table("sync_runs", [{"id": "run-2"}, {"id": "run-3"}])
    fake_supabase.set_table(
        "sync_run_items",
        [{"account_id": "acc-1"}, {"account_id": "acc-2"}, {"account_id": None}],
    )
    out = handler.list_later_written_account_ids(
        sample_user_id, date(2026, 9, 30), "2026-10-01T10:00:00+00:00"
    )
    assert out == {"acc-1", "acc-2"}

    runs_chain = fake_supabase._tables["sync_runs"].calls
    runs_eq = {c[1][0]: c[1][1] for c in runs_chain if c[0] == "eq"}
    assert runs_eq == {"user_id": sample_user_id, "as_of_date": "2026-09-30"}
    assert ("gt", ("started_at", "2026-10-01T10:00:00+00:00"), {}) in runs_chain
    assert ("is_", ("undone_at", "null"), {}) in runs_chain

    items_chain = fake_supabase._tables["sync_run_items"].calls
    assert ("in_", ("sync_run_id", ["run-2", "run-3"]), {}) in items_chain
    assert ("eq", ("outcome", "written"), {}) in items_chain


def test_list_later_written_account_ids_no_later_runs(handler, fake_supabase):
    fake_supabase.set_table("sync_runs", [])
    assert handler.list_later_written_account_ids("u1", "2026-09-30", "t") == set()
    assert "sync_run_items" not in fake_supabase._tables


def test_list_later_written_account_ids_raises_on_db_error(handler, fake_supabase):
    fake_supabase.table.side_effect = RuntimeError("db down")
    with pytest.raises(RuntimeError):
        handler.list_later_written_account_ids("u1", "2026-09-30", "t")


def test_list_user_ids_with_active_connections(handler, fake_supabase):
    fake_supabase.set_table(
        "provider_connections",
        [
            {"user_id": "u1", "status": "active"},
            {"user_id": "u2", "status": "active"},
            {"user_id": "u1", "status": "active"},
        ],
    )
    assert handler.list_user_ids_with_active_connections() == ["u1", "u2"]
