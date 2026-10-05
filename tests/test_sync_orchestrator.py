import json
from datetime import date
from decimal import Decimal

from utils.providers.base import (
    NormalizedBalance,
    ProviderAuthError,
    ProviderError,
    ProviderTransientError,
)
from utils.sync.orchestrator import default_credential_refreshers, run_sync

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
        self.credential_updates = []
        self.list_kwargs = []
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

    def list_provider_connections(self, user_id, **kwargs):
        self.list_kwargs.append(("connections", kwargs))
        return [dict(c) for c in self.connections]

    def list_account_mappings(self, user_id, **kwargs):
        self.list_kwargs.append(("mappings", kwargs))
        return list(self.mappings)

    def update_provider_connection_credentials(self, connection_id, credentials_encrypted):
        self.credential_updates.append((connection_id, credentials_encrypted))

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
    def __init__(self, balances=None, error=None, errors=None):
        self.balances = balances or []
        self.error = error
        self.errors = list(errors or [])
        self.seen_connections = []

    def list_balances(self, connection):
        self.seen_connections.append(dict(connection))
        if self.errors:
            err = self.errors.pop(0)
            if err is not None:
                raise err
            return self.balances
        if self.error:
            raise self.error
        return self.balances


class FakeRefresher:
    """Stand-in for an Open Banking token refresher: (credentials, force) -> credentials."""

    def __init__(self, on_expired=None, on_force=None, error_on_force=None, error_on_check=None):
        self.on_expired = on_expired
        self.on_force = on_force
        self.error_on_force = error_on_force
        self.error_on_check = error_on_check
        self.calls = []

    def __call__(self, credentials, force):
        self.calls.append((dict(credentials), force))
        if force:
            if self.error_on_force:
                raise self.error_on_force
            return dict(self.on_force) if self.on_force is not None else dict(credentials)
        if self.error_on_check:
            raise self.error_on_check
        return dict(self.on_expired) if self.on_expired is not None else dict(credentials)


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


def run(db, providers, convert=None, trigger="manual", refreshers=None, decrypted=None):
    return run_sync(
        db,
        USER,
        AS_OF,
        trigger,
        providers=providers,
        convert_to_gbp=convert or (lambda amount, currency: float(amount)),
        decrypt_credentials=lambda token: json.dumps(decrypted or {"api_key": "k"}),
        encrypt_credentials=lambda plaintext: f"enc:{plaintext}",
        credential_refreshers=refreshers if refreshers is not None else {},
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


def test_needs_reauth_connection_records_error_per_mapped_account():
    db = FakeDb(
        [conn(status="needs_reauth")],
        [mapping(ext="ext-1", account_id="acc-1"), mapping(ext="ext-2", account_id="acc-2")],
    )
    provider = FakeProvider([bal()])
    result = run(db, {"trading212": provider})
    assert provider.seen_connections == []
    assert db.saved == []
    assert [(i["outcome"], i["account_id"], i["reason"]) for i in db.items] == [
        ("error", "acc-1", "needs_reauth"),
        ("error", "acc-2", "needs_reauth"),
    ]
    assert result["status"] == "failed"
    assert result["error_count"] == 2
    assert db.statuses == {}


def test_error_connection_records_connection_error_and_isolated_from_active():
    db = FakeDb(
        [conn("c1", status="error"), conn("c2", "open_banking")],
        [mapping("c1", "ext-1", "acc-1"), mapping("c2", "ext-2", "acc-2")],
    )
    providers = {
        "trading212": FakeProvider([bal()]),
        "open_banking": FakeProvider([bal(ext="ext-2")]),
    }
    result = run(db, providers)
    assert providers["trading212"].seen_connections == []
    errors = [i for i in db.items if i["outcome"] == "error"]
    assert [(i["account_id"], i["reason"]) for i in errors] == [("acc-1", "connection_error")]
    assert db.saved == [("acc-2", "2026-09-30", 100.0)]
    assert result["status"] == "partial"


def test_disabled_connection_mapped_accounts_skipped_not_errors():
    db = FakeDb([conn(status="disabled")], [mapping()])
    result = run(db, {"trading212": FakeProvider([bal()])})
    assert [(i["outcome"], i["reason"]) for i in db.items] == [("skipped", "connection_disabled")]
    assert result["status"] == "success"


def test_non_active_connection_without_mappings_records_nothing():
    db = FakeDb([conn(status="needs_reauth")], [])
    result = run(db, {"trading212": FakeProvider([bal()])})
    assert db.items == []
    assert result["status"] == "success"


def test_connection_failure_records_error_per_mapped_account():
    db = FakeDb(
        [conn()],
        [mapping(ext="ext-1", account_id="acc-1"), mapping(ext="ext-2", account_id="acc-2")],
    )
    result = run(db, {"trading212": FakeProvider(error=ProviderAuthError("bad"))})
    assert [(i["account_id"], i["external_account_id"]) for i in db.items] == [
        ("acc-1", "ext-1"),
        ("acc-2", "ext-2"),
    ]
    assert all(i["reason"].startswith("provider_auth_error") for i in db.items)
    assert result["error_count"] == 2


def test_transient_provider_error_keeps_connection_active():
    db = FakeDb([conn()], [mapping()])
    result = run(
        db, {"trading212": FakeProvider(error=ProviderTransientError("HTTP 429"))}
    )
    status, last_error = db.statuses["c1"]
    assert status == "active"
    assert last_error.startswith("provider_unavailable")
    assert db.items[0]["outcome"] == "error"
    assert db.items[0]["account_id"] == "acc-1"
    assert db.items[0]["reason"].startswith("provider_unavailable")
    assert result["status"] == "failed"
    assert db.synced == []


def test_sync_reads_connections_and_mappings_strictly():
    db = FakeDb([conn()], [mapping()])
    run(db, {"trading212": FakeProvider([bal()])})
    assert db.list_kwargs == [("connections", {"strict": True}), ("mappings", {"strict": True})]


def test_connection_list_failure_fails_run():
    class BrokenDb(FakeDb):
        def list_provider_connections(self, user_id, **kwargs):
            raise RuntimeError("db down")

    db = BrokenDb([conn()], [mapping()])
    result = run(db, {"trading212": FakeProvider([bal()])})
    assert result["status"] == "failed"
    assert result["notes"].startswith("run_aborted")


# --- Open Banking token refresh ------------------------------------------

OB_CREDS = {"access_token": "old", "refresh_token": "r", "requisition_id": "req"}
OB_NEW_CREDS = {**OB_CREDS, "access_token": "new", "access_expires_at": 123}


def ob_db(**kwargs):
    return FakeDb([conn("c2", "open_banking")], [mapping("c2", "ext-2", "acc-2")], **kwargs)


def test_expired_open_banking_token_refreshed_then_written():
    db = ob_db()
    provider = FakeProvider([bal(ext="ext-2", amount="75")])
    refresher = FakeRefresher(on_expired=OB_NEW_CREDS)
    result = run(db, {"open_banking": provider}, refreshers={"open_banking": refresher}, decrypted=OB_CREDS)

    assert refresher.calls == [(OB_CREDS, False)]
    assert provider.seen_connections[0]["credentials"] == OB_NEW_CREDS
    assert db.credential_updates == [("c2", f"enc:{json.dumps(OB_NEW_CREDS)}")]
    assert db.saved == [("acc-2", "2026-09-30", 75.0)]
    assert db.statuses == {}
    assert db.synced == ["c2"]
    assert result["status"] == "success"


def test_unchanged_open_banking_credentials_not_persisted():
    db = ob_db()
    refresher = FakeRefresher()
    run(
        db,
        {"open_banking": FakeProvider([bal(ext="ext-2")])},
        refreshers={"open_banking": refresher},
        decrypted=OB_CREDS,
    )
    assert refresher.calls == [(OB_CREDS, False)]
    assert db.credential_updates == []
    assert db.saved


def test_open_banking_auth_error_refreshes_once_and_retries():
    db = ob_db()
    provider = FakeProvider([bal(ext="ext-2", amount="60")], errors=[ProviderAuthError("401"), None])
    refresher = FakeRefresher(on_force=OB_NEW_CREDS)
    result = run(db, {"open_banking": provider}, refreshers={"open_banking": refresher}, decrypted=OB_CREDS)

    assert [force for _, force in refresher.calls] == [False, True]
    assert [c["credentials"]["access_token"] for c in provider.seen_connections] == ["old", "new"]
    assert db.credential_updates == [("c2", f"enc:{json.dumps(OB_NEW_CREDS)}")]
    assert db.saved == [("acc-2", "2026-09-30", 60.0)]
    assert "c2" not in db.statuses
    assert result["status"] == "success"


def test_open_banking_refresh_failure_marks_needs_reauth():
    db = ob_db()
    provider = FakeProvider(error=ProviderAuthError("401"))
    refresher = FakeRefresher(error_on_force=ProviderAuthError("refresh rejected"))
    result = run(db, {"open_banking": provider}, refreshers={"open_banking": refresher}, decrypted=OB_CREDS)

    assert len(provider.seen_connections) == 1
    assert db.statuses["c2"][0] == "needs_reauth"
    assert db.items[0]["account_id"] == "acc-2"
    assert db.items[0]["reason"].startswith("provider_auth_error")
    assert db.credential_updates == []
    assert db.saved == []
    assert result["status"] == "failed"


def test_open_banking_still_rejected_after_refresh_marks_needs_reauth():
    db = ob_db()
    provider = FakeProvider(error=ProviderAuthError("401"))
    refresher = FakeRefresher(on_force=OB_NEW_CREDS)
    result = run(db, {"open_banking": provider}, refreshers={"open_banking": refresher}, decrypted=OB_CREDS)

    assert len(provider.seen_connections) == 2
    assert [force for _, force in refresher.calls] == [False, True]
    assert db.statuses["c2"][0] == "needs_reauth"
    assert result["status"] == "failed"


def test_open_banking_pre_fetch_refresh_failure_marks_needs_reauth():
    db = ob_db()
    provider = FakeProvider([bal(ext="ext-2")])
    refresher = FakeRefresher(error_on_check=ProviderAuthError("refresh token expired"))
    run(db, {"open_banking": provider}, refreshers={"open_banking": refresher}, decrypted=OB_CREDS)

    assert provider.seen_connections == []
    assert db.statuses["c2"][0] == "needs_reauth"


def test_open_banking_transient_refresh_failure_keeps_active():
    db = ob_db()
    refresher = FakeRefresher(error_on_check=ProviderTransientError("503"))
    result = run(
        db,
        {"open_banking": FakeProvider([bal(ext="ext-2")])},
        refreshers={"open_banking": refresher},
        decrypted=OB_CREDS,
    )
    assert db.statuses["c2"][0] == "active"
    assert db.items[0]["reason"].startswith("provider_unavailable")
    assert result["status"] == "failed"


def test_refreshed_credentials_persist_failure_does_not_block_write():
    class PersistFailDb(FakeDb):
        def update_provider_connection_credentials(self, connection_id, credentials_encrypted):
            raise RuntimeError("write failed")

    db = PersistFailDb([conn("c2", "open_banking")], [mapping("c2", "ext-2", "acc-2")])
    result = run(
        db,
        {"open_banking": FakeProvider([bal(ext="ext-2")])},
        refreshers={"open_banking": FakeRefresher(on_expired=OB_NEW_CREDS)},
        decrypted=OB_CREDS,
    )
    assert db.saved == [("acc-2", "2026-09-30", 100.0)]
    assert result["status"] == "success"


def test_refresher_only_used_for_its_provider():
    db = FakeDb([conn("c1", "trading212")], [mapping()])
    refresher = FakeRefresher(on_expired=OB_NEW_CREDS)
    run(db, {"trading212": FakeProvider([bal()])}, refreshers={"open_banking": refresher})
    assert refresher.calls == []


def test_default_credential_refreshers_use_gocardless_env(mocker, monkeypatch):
    monkeypatch.setenv("GOCARDLESS_SECRET_ID", "env-sid")
    monkeypatch.setenv("GOCARDLESS_SECRET_KEY", "env-skey")
    ensure = mocker.patch(
        "utils.providers.open_banking.ensure_access_token", return_value={"access_token": "x"}
    )
    refreshers = default_credential_refreshers()
    assert refreshers["open_banking"]({"a": 1}, True) == {"access_token": "x"}
    ensure.assert_called_once_with({"a": 1}, "env-sid", "env-skey", force=True)


def test_default_credential_refreshers_explicit_secrets_override_env(mocker, monkeypatch):
    monkeypatch.setenv("GOCARDLESS_SECRET_ID", "env-sid")
    monkeypatch.setenv("GOCARDLESS_SECRET_KEY", "env-skey")
    ensure = mocker.patch("utils.providers.open_banking.ensure_access_token", return_value={})
    default_credential_refreshers("sid", "skey")["open_banking"]({}, False)
    ensure.assert_called_once_with({}, "sid", "skey", force=False)


def test_default_credential_refreshers_without_secrets(mocker, monkeypatch):
    monkeypatch.delenv("GOCARDLESS_SECRET_ID", raising=False)
    monkeypatch.delenv("GOCARDLESS_SECRET_KEY", raising=False)
    ensure = mocker.patch("utils.providers.open_banking.ensure_access_token", return_value={})
    default_credential_refreshers()["open_banking"]({}, False)
    ensure.assert_called_once_with({}, None, None, force=False)


class _HttpResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _gocardless_http(mocker, *, refresh_status=200):
    """Mock GoCardless: only the "new" access token is accepted for data calls."""
    posts = []

    def fake_get(url, headers=None, **kwargs):
        if headers.get("Authorization") != "Bearer new":
            return _HttpResp(401)
        if url.endswith("/requisitions/req/"):
            return _HttpResp(200, {"accounts": ["ext-2"]})
        if url.endswith("/accounts/ext-2/details/"):
            return _HttpResp(200, {"account": {"name": "Current", "currency": "GBP"}})
        if url.endswith("/accounts/ext-2/balances/"):
            return _HttpResp(
                200,
                {"balances": [{"balanceType": "closingBooked", "balanceAmount": {"amount": "321.00", "currency": "GBP"}}]},
            )
        raise AssertionError(url)

    def fake_post(url, json=None, **kwargs):
        posts.append(url)
        if url.endswith("/token/refresh/"):
            if refresh_status != 200:
                return _HttpResp(refresh_status)
            return _HttpResp(200, {"access": "new", "access_expires": 86400})
        raise AssertionError(url)

    mocker.patch("utils.providers.open_banking.requests.get", side_effect=fake_get)
    mocker.patch("utils.providers.open_banking.requests.post", side_effect=fake_post)
    return posts


def _run_open_banking_end_to_end(db, monkeypatch):
    from utils.providers.open_banking import OpenBankingProvider

    monkeypatch.delenv("GOCARDLESS_SECRET_ID", raising=False)
    monkeypatch.delenv("GOCARDLESS_SECRET_KEY", raising=False)
    return run_sync(
        db,
        USER,
        AS_OF,
        "scheduled",
        providers={"open_banking": OpenBankingProvider()},
        convert_to_gbp=lambda a, c: float(a),
        decrypt_credentials=lambda t: json.dumps(OB_CREDS),
        encrypt_credentials=lambda p: f"enc:{p}",
    )


def test_end_to_end_expired_open_banking_token_refreshed_and_written(mocker, monkeypatch):
    posts = _gocardless_http(mocker)
    db = ob_db()
    result = _run_open_banking_end_to_end(db, monkeypatch)

    assert [p.rsplit("/api/v2", 1)[1] for p in posts] == ["/token/refresh/"]
    assert db.saved == [("acc-2", "2026-09-30", 321.0)]
    (cid, stored), = db.credential_updates
    assert cid == "c2"
    stored_creds = json.loads(stored.removeprefix("enc:"))
    assert stored_creds["access_token"] == "new"
    assert stored_creds["refresh_token"] == "r"
    assert "access_expires_at" in stored_creds
    assert "c2" not in db.statuses
    assert result["status"] == "success"


def test_end_to_end_open_banking_refresh_rejected_marks_needs_reauth(mocker, monkeypatch):
    _gocardless_http(mocker, refresh_status=401)
    db = ob_db()
    result = _run_open_banking_end_to_end(db, monkeypatch)

    assert db.saved == []
    assert db.credential_updates == []
    assert db.statuses["c2"][0] == "needs_reauth"
    assert db.items[0]["account_id"] == "acc-2"
    assert result["status"] == "failed"


def test_run_sync_uses_default_refreshers_when_none_given(mocker):
    refresher = FakeRefresher(on_expired=OB_NEW_CREDS)
    factory = mocker.patch(
        "utils.sync.orchestrator.default_credential_refreshers",
        return_value={"open_banking": refresher},
    )
    db = ob_db()
    run_sync(
        db,
        USER,
        AS_OF,
        "scheduled",
        providers={"open_banking": FakeProvider([bal(ext="ext-2")])},
        convert_to_gbp=lambda a, c: float(a),
        decrypt_credentials=lambda t: json.dumps(OB_CREDS),
        encrypt_credentials=lambda p: p,
    )
    factory.assert_called_once_with()
    assert refresher.calls == [(OB_CREDS, False)]


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


class FailingSaveDb(FakeDb):
    def __init__(self, *args, fail_accounts=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_accounts = set(fail_accounts)

    def save_account_value(self, account_id, date_str, value):
        if account_id in self.fail_accounts:
            raise RuntimeError("db down postgres://user:pw@host/db")
        return super().save_account_value(account_id, date_str, value)


def test_save_failure_is_isolated_and_run_finalized():
    db = FailingSaveDb(
        [conn("c1", "trading212"), conn("c2", "open_banking")],
        [
            mapping("c1", "ext-1", "acc-1"),
            mapping("c1", "ext-2", "acc-2"),
            mapping("c2", "ext-3", "acc-3"),
        ],
        fail_accounts={"acc-1"},
    )
    providers = {
        "trading212": FakeProvider([bal("ext-1"), bal("ext-2", amount="20")]),
        "open_banking": FakeProvider([bal("ext-3", amount="30")]),
    }
    result = run(db, providers)

    assert db.saved == [("acc-2", "2026-09-30", 20.0), ("acc-3", "2026-09-30", 30.0)]
    assert db.finalized is not None
    assert result["status"] == "partial"
    assert result["written_count"] == 2
    assert result["error_count"] == 1
    errors = [i for i in db.items if i["outcome"] == "error"]
    assert len(errors) == 1
    assert errors[0]["account_id"] == "acc-1"
    assert errors[0]["reason"].startswith("write_failed")
    assert "postgres" not in errors[0]["reason"]
    assert db.synced == ["c1", "c2"]


def test_converter_exception_is_isolated():
    db = FakeDb([conn()], [mapping(), mapping(ext="ext-2", account_id="acc-2")])

    def convert(amount, currency):
        if currency == "USD":
            raise ValueError("rate api key=SECRET")
        return amount

    result = run(
        db,
        {"trading212": FakeProvider([bal(currency="USD"), bal("ext-2")])},
        convert=convert,
    )
    assert db.saved == [("acc-2", "2026-09-30", 100.0)]
    assert result["status"] == "partial"
    assert "SECRET" not in str(db.items)


def test_unexpected_run_failure_still_finalizes():
    class BrokenDb(FakeDb):
        def list_account_mappings(self, user_id, **kwargs):
            raise RuntimeError("connection reset")

    db = BrokenDb([conn()], [mapping()])
    result = run(db, {"trading212": FakeProvider([bal()])})
    assert db.finalized is not None
    assert result["status"] == "failed"
    assert result["error_count"] == 1
    assert result["notes"] == "run_aborted: RuntimeError"


def test_item_recording_failure_does_not_abort_run():
    class ItemFailDb(FakeDb):
        def add_sync_run_item(self, *args, **kwargs):
            raise RuntimeError("insert failed")

    db = ItemFailDb([conn()], [mapping()])
    result = run(db, {"trading212": FakeProvider([bal()])})
    assert db.saved
    assert result["status"] == "success"
    assert result["written_count"] == 1


MESSY = "401 for https://api.example.com/v1?api_key=SECRETKEY123 Bearer TOKEN-abc password=hunter2"


def assert_clean(text):
    for needle in ("SECRETKEY123", "TOKEN-abc", "hunter2", "http", "api_key", "Bearer"):
        assert needle not in text


def test_provider_error_reasons_do_not_leak_credentials():
    for exc, status in (
        (ProviderAuthError(MESSY), "needs_reauth"),
        (ProviderError(MESSY), "error"),
        (RuntimeError(MESSY), "error"),
    ):
        db = FakeDb([conn()], [mapping()])
        run(db, {"trading212": FakeProvider(error=exc)})
        assert db.statuses["c1"][0] == status
        assert_clean(db.statuses["c1"][1])
        assert_clean(db.items[0]["reason"])


def test_decrypt_failure_reason_is_sanitized():
    def bad_decrypt(token):
        raise ValueError(MESSY)

    db = FakeDb([conn()], [mapping()])
    run_sync(
        db,
        USER,
        AS_OF,
        "manual",
        providers={"trading212": FakeProvider([bal()])},
        convert_to_gbp=lambda a, c: a,
        decrypt_credentials=bad_decrypt,
    )
    assert db.items[0]["reason"].startswith("decrypt_failed")
    assert_clean(db.items[0]["reason"])
    assert_clean(db.statuses["c1"][1])


def test_logs_do_not_leak_credentials(caplog):
    db = FakeDb([conn()], [mapping()])
    run(db, {"trading212": FakeProvider(error=RuntimeError(MESSY))})
    assert_clean(caplog.text)
