from datetime import date
from decimal import Decimal

from utils.providers.base import NormalizedBalance, ProviderAuthError, ProviderError
from utils.sync.orchestrator import run_sync

USER = "user-1"
AS_OF = date(2026, 9, 30)


class FakeDb:
    def __init__(self, connections=None, mappings=None, values=None):
        self.connections = connections or []
        self.mappings = mappings or []
        self.values = dict(values or {})
        self.saved = []
        self.items = []
        self.statuses = {}
        self.synced = []
        self.run = None
        self.finalized = None

    def create_sync_run(self, user_id, trigger, as_of_date):
        self.run = {
            "id": "run-1",
            "user_id": user_id,
            "trigger": trigger,
            "as_of_date": as_of_date.isoformat(),
            "status": "running",
        }
        return dict(self.run)

    def finalize_sync_run(
        self, run_id, status, written_count, skipped_count, error_count, notes=None
    ):
        self.finalized = {
            **self.run,
            "id": run_id,
            "status": status,
            "written_count": written_count,
            "skipped_count": skipped_count,
            "error_count": error_count,
            "notes": notes,
        }
        return dict(self.finalized)

    def add_sync_run_item(self, sync_run_id, provider, outcome, **kwargs):
        item = {"sync_run_id": sync_run_id, "provider": provider, "outcome": outcome, **kwargs}
        self.items.append(item)
        return item

    def list_provider_connections(self, user_id):
        return [dict(c) for c in self.connections]

    def list_account_mappings(self, user_id):
        return list(self.mappings)

    def get_account_value(self, account_id, date_str):
        return self.values.get((account_id, date_str))

    def save_account_value(self, account_id, date_str, value):
        self.values[(account_id, date_str)] = value
        self.saved.append((account_id, date_str, value))
        return {}

    def update_provider_connection_status(self, connection_id, status, last_error=None):
        self.statuses[connection_id] = (status, last_error)
        return {}

    def touch_provider_connection_synced(self, connection_id):
        self.synced.append(connection_id)


class FakeProvider:
    def __init__(self, balances=None, error=None):
        self.balances = balances or []
        self.error = error
        self.seen_connections = []

    def list_balances(self, connection):
        self.seen_connections.append(connection)
        if self.error:
            raise self.error
        return self.balances


def conn(cid="c1", provider="trading212", status="active"):
    return {
        "id": cid,
        "user_id": USER,
        "provider": provider,
        "status": status,
        "credentials_encrypted": "enc",
    }


def mapping(cid="c1", ext="ext-1", account_id="acc-1"):
    return {
        "id": f"m-{cid}-{ext}",
        "provider_connection_id": cid,
        "external_account_id": ext,
        "account_id": account_id,
    }


def bal(ext="ext-1", currency="GBP", amount="100.00"):
    return NormalizedBalance(ext, "Name", currency, Decimal(amount))


def run(db, providers, convert=None, trigger="manual"):
    return run_sync(
        db,
        USER,
        AS_OF,
        trigger,
        providers=providers,
        convert_to_gbp=convert or (lambda amount, currency: float(amount)),
        decrypt_credentials=lambda token: '{"api_key": "k"}',
    )


def test_mapped_balance_is_written_in_gbp():
    db = FakeDb([conn()], [mapping()])
    result = run(db, {"trading212": FakeProvider([bal(amount="123.45")])})
    assert db.saved == [("acc-1", "2026-09-30", 123.45)]
    assert [i["outcome"] for i in db.items] == ["written"]
    assert db.items[0]["account_id"] == "acc-1"
    assert db.items[0]["new_value_gbp"] == 123.45
    assert db.items[0]["had_previous"] is False
    assert result["status"] == "success"
    assert result["written_count"] == 1
    assert db.synced == ["c1"]


def test_credentials_decrypted_onto_connection():
    db = FakeDb([conn()], [mapping()])
    provider = FakeProvider([bal()])
    run(db, {"trading212": provider})
    assert provider.seen_connections[0]["credentials"] == {"api_key": "k"}


def test_unmapped_balance_is_skipped():
    db = FakeDb([conn()], [])
    result = run(db, {"trading212": FakeProvider([bal(ext="other")])})
    assert db.saved == []
    assert db.items[0]["outcome"] == "skipped"
    assert db.items[0]["reason"] == "unmapped"
    assert db.items[0]["external_account_id"] == "other"
    assert result["status"] == "success"
    assert result["skipped_count"] == 1


def test_auth_error_marks_needs_reauth_and_run_failed():
    db = FakeDb([conn()], [mapping()])
    result = run(db, {"trading212": FakeProvider(error=ProviderAuthError("bad key"))})
    assert db.statuses["c1"][0] == "needs_reauth"
    assert db.items[0]["outcome"] == "error"
    assert result["status"] == "failed"
    assert result["error_count"] == 1
    assert db.synced == []


def test_auth_error_isolated_other_provider_still_writes_partial():
    db = FakeDb(
        [conn("c1", "trading212"), conn("c2", "open_banking")],
        [mapping("c1", "ext-1", "acc-1"), mapping("c2", "ext-2", "acc-2")],
    )
    providers = {
        "trading212": FakeProvider(error=ProviderAuthError("expired")),
        "open_banking": FakeProvider([bal(ext="ext-2", amount="50")]),
    }
    result = run(db, providers)
    assert db.statuses["c1"][0] == "needs_reauth"
    assert db.saved == [("acc-2", "2026-09-30", 50.0)]
    assert result["status"] == "partial"
    assert db.synced == ["c2"]
    assert not any(i["reason"] == "not_returned" for i in db.items if "reason" in i)


def test_provider_error_marks_connection_error():
    db = FakeDb([conn()], [mapping()])
    result = run(db, {"trading212": FakeProvider(error=ProviderError("boom"))})
    assert db.statuses["c1"][0] == "error"
    assert result["status"] == "failed"


def test_non_active_connection_ignored():
    db = FakeDb([conn(status="needs_reauth")], [mapping()])
    provider = FakeProvider([bal()])
    result = run(db, {"trading212": provider})
    assert provider.seen_connections == []
    assert db.items == []
    assert result["status"] == "success"


def test_currency_conversion_uses_injected_converter():
    db = FakeDb([conn()], [mapping()])
    calls = []

    def convert(amount, currency):
        calls.append((amount, currency))
        return 80.0

    run(db, {"trading212": FakeProvider([bal(currency="USD", amount="100")])}, convert)
    assert calls == [(100.0, "USD")]
    assert db.saved == [("acc-1", "2026-09-30", 80.0)]
    assert db.items[0]["external_currency"] == "USD"
    assert db.items[0]["external_amount"] == 100.0


def test_conversion_failure_is_error_item_and_not_written():
    db = FakeDb([conn()], [mapping()])
    result = run(
        db,
        {"trading212": FakeProvider([bal(currency="XYZ")])},
        convert=lambda amount, currency: None,
    )
    assert db.saved == []
    assert db.items[0]["outcome"] == "error"
    assert db.items[0]["reason"] == "conversion_failed"
    assert [i["reason"] for i in db.items] == ["conversion_failed"]
    assert result["status"] == "failed"


def test_zero_amount_is_written():
    db = FakeDb([conn()], [mapping()])
    result = run(db, {"trading212": FakeProvider([bal(amount="0")])})
    assert db.saved == [("acc-1", "2026-09-30", 0.0)]
    assert db.items[0]["outcome"] == "written"
    assert result["written_count"] == 1


def test_mapped_but_not_returned_is_skipped():
    db = FakeDb([conn()], [mapping(ext="ext-1"), mapping(ext="gone", account_id="acc-2")])
    result = run(db, {"trading212": FakeProvider([bal(ext="ext-1")])})
    assert db.saved == [("acc-1", "2026-09-30", 100.0)]
    skipped = [i for i in db.items if i["outcome"] == "skipped"]
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "not_returned"
    assert skipped[0]["account_id"] == "acc-2"
    assert skipped[0]["external_account_id"] == "gone"
    assert result["skipped_count"] == 1
    assert result["status"] == "success"


def test_existing_value_overwritten_with_previous_recorded():
    db = FakeDb([conn()], [mapping()], values={("acc-1", "2026-09-30"): 42.5})
    run(db, {"trading212": FakeProvider([bal(amount="100")])})
    assert db.saved == [("acc-1", "2026-09-30", 100.0)]
    item = db.items[0]
    assert item["had_previous"] is True
    assert item["previous_value_gbp"] == 42.5
    assert item["new_value_gbp"] == 100.0


def test_existing_zero_value_counts_as_previous():
    db = FakeDb([conn()], [mapping()], values={("acc-1", "2026-09-30"): 0.0})
    run(db, {"trading212": FakeProvider([bal(amount="10")])})
    assert db.items[0]["had_previous"] is True
    assert db.items[0]["previous_value_gbp"] == 0.0


def test_unknown_provider_is_error_item():
    db = FakeDb([conn()], [mapping()])
    result = run(db, {})
    assert db.items[0]["outcome"] == "error"
    assert result["status"] == "failed"


def test_default_providers_registry_used_when_none(mocker):
    fake = FakeProvider([bal()])
    mocker.patch("utils.sync.orchestrator.default_providers", return_value={"trading212": fake})
    db = FakeDb([conn()], [mapping()])
    result = run_sync(
        db,
        USER,
        AS_OF,
        "scheduled",
        convert_to_gbp=lambda a, c: float(a),
        decrypt_credentials=lambda t: "{}",
    )
    assert result["status"] == "success"
    assert db.saved
