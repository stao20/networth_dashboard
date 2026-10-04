from datetime import date

import pytest

from utils.sync.undo import undo_sync_run

USER = "user-1"
OTHER = "user-2"
AS_OF = date(2026, 9, 30)
AS_OF_STR = "2026-09-30"
RUN_ID = "run-1"


class FakeDb:
    def __init__(self, run=None, items=None, values=None):
        self.run = run
        self.items = list(items or [])
        self.values = dict(values or {})
        self.saved = []
        self.deleted = []
        self.undone_notes = None

    def get_sync_run(self, run_id):
        if self.run and self.run.get("id") == run_id:
            return dict(self.run)
        return None

    def list_sync_run_items(self, run_id):
        return [dict(i) for i in self.items if i.get("sync_run_id") == run_id]

    def get_account_value(self, account_id, date_str):
        return self.values.get((account_id, date_str))

    def save_account_value(self, account_id, date_str, value):
        self.values[(account_id, date_str)] = value
        self.saved.append((account_id, date_str, value))
        return {}

    def delete_account_value(self, account_id, date_str):
        self.deleted.append((account_id, date_str))
        self.values.pop((account_id, date_str), None)
        return {}

    def mark_sync_run_undone(self, run_id, notes=None):
        self.undone_notes = notes
        return {
            **(self.run or {}),
            "id": run_id,
            "undone_at": "2026-10-01T12:00:00Z",
            "notes": notes,
        }


def base_run(user_id=USER, as_of=AS_OF):
    return {
        "id": RUN_ID,
        "user_id": user_id,
        "as_of_date": as_of,
        "status": "success",
    }


def written_item(
    account_id="acc-1",
    new_value=1000.0,
    previous_value=500.0,
    had_previous=True,
):
    return {
        "sync_run_id": RUN_ID,
        "provider": "trading212",
        "outcome": "written",
        "account_id": account_id,
        "new_value_gbp": new_value,
        "previous_value_gbp": previous_value,
        "had_previous": had_previous,
    }


def test_undo_restores_previous_when_had_previous():
    db = FakeDb(
        run=base_run(),
        items=[written_item(had_previous=True, new_value=1000.0, previous_value=500.0)],
        values={("acc-1", AS_OF_STR): 1000.0},
    )
    result = undo_sync_run(db, USER, RUN_ID)
    assert result["restored"] == 1
    assert result["deleted"] == 0
    assert result["skipped"] == 0
    assert db.saved == [("acc-1", AS_OF_STR, 500.0)]
    assert db.deleted == []
    assert db.values[("acc-1", AS_OF_STR)] == 500.0


def test_undo_deletes_value_when_no_previous():
    db = FakeDb(
        run=base_run(),
        items=[written_item(had_previous=False, new_value=1000.0)],
        values={("acc-1", AS_OF_STR): 1000.0},
    )
    result = undo_sync_run(db, USER, RUN_ID)
    assert result["restored"] == 0
    assert result["deleted"] == 1
    assert result["skipped"] == 0
    assert db.deleted == [("acc-1", AS_OF_STR)]
    assert db.saved == []
    assert ("acc-1", AS_OF_STR) not in db.values


def test_undo_skips_when_current_differs_from_new():
    db = FakeDb(
        run=base_run(),
        items=[written_item(had_previous=True, new_value=1000.0, previous_value=500.0)],
        values={("acc-1", AS_OF_STR): 999.0},
    )
    result = undo_sync_run(db, USER, RUN_ID)
    assert result["restored"] == 0
    assert result["deleted"] == 0
    assert result["skipped"] == 1
    assert db.saved == []
    assert db.deleted == []


def test_undo_raises_permission_error_for_wrong_user():
    db = FakeDb(run=base_run(user_id=USER), items=[])
    with pytest.raises(PermissionError, match="Sync run not found for user"):
        undo_sync_run(db, OTHER, RUN_ID)


def test_undo_marks_run_undone_with_summary_notes():
    db = FakeDb(
        run=base_run(),
        items=[written_item(had_previous=False, new_value=1000.0)],
        values={("acc-1", AS_OF_STR): 1000.0},
    )
    result = undo_sync_run(db, USER, RUN_ID)
    assert db.undone_notes == "Undo: restored=0, deleted=1, skipped=0"
    assert result["run"]["undone_at"] == "2026-10-01T12:00:00Z"
    assert result["run"]["notes"] == db.undone_notes
