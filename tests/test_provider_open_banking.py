import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from utils.providers.base import ProviderAuthError, ProviderError, ProviderTransientError
from utils.providers.open_banking import OpenBankingProvider, _pick_balance, ensure_access_token

BALANCES_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "gocardless_balances.json").read_text()
)
DETAILS_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "gocardless_account_details.json").read_text()
)

ACCOUNT_ID = "acc-uuid-1111"
REQUISITION_ID = "req-abc-123"
BASE = "https://bankaccountdata.gocardless.com/api/v2"
NOW = 1_800_000_000


def _connection():
    return {
        "credentials": {
            "access_token": "access-tok",
            "refresh_token": "refresh-tok",
            "requisition_id": REQUISITION_ID,
        }
    }


def _resp(status_code, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    return resp


def test_list_balances_fetches_requisition_details_and_balances(mocker):
    def fake_get(url, **kwargs):
        resp = MagicMock()
        if f"/requisitions/{REQUISITION_ID}/" in url:
            resp.status_code = 200
            resp.json.return_value = {"accounts": [ACCOUNT_ID]}
        elif f"/accounts/{ACCOUNT_ID}/details/" in url:
            resp.status_code = 200
            resp.json.return_value = DETAILS_FIXTURE
        elif f"/accounts/{ACCOUNT_ID}/balances/" in url:
            resp.status_code = 200
            resp.json.return_value = BALANCES_FIXTURE
        else:
            raise AssertionError(f"Unexpected URL: {url}")
        return resp

    mocker.patch("utils.providers.open_banking.requests.get", side_effect=fake_get)

    provider = OpenBankingProvider()
    balances = provider.list_balances(_connection())

    assert len(balances) == 1
    assert balances[0].external_account_id == ACCOUNT_ID
    assert balances[0].currency == "GBP"
    assert balances[0].amount == Decimal("1300.00")
    assert balances[0].raw["selected_balance"]["balanceType"] == "closingBooked"
    assert balances[0].name == "Main Current"


def test_401_raises_auth_error(mocker):
    resp = MagicMock()
    resp.status_code = 401
    resp.text = "Unauthorized"
    mocker.patch("utils.providers.open_banking.requests.get", return_value=resp)

    with pytest.raises(ProviderAuthError):
        OpenBankingProvider().list_balances(_connection())


@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
def test_rate_limit_and_server_errors_are_transient(mocker, status_code):
    mocker.patch(
        "utils.providers.open_banking.requests.get", return_value=_resp(status_code)
    )
    with pytest.raises(ProviderTransientError):
        OpenBankingProvider().list_balances(_connection())


def test_timeout_is_transient(mocker):
    mocker.patch(
        "utils.providers.open_banking.requests.get",
        side_effect=requests.Timeout("slow"),
    )
    with pytest.raises(ProviderTransientError):
        OpenBankingProvider().list_balances(_connection())


def test_client_error_is_not_transient(mocker):
    mocker.patch("utils.providers.open_banking.requests.get", return_value=_resp(404))
    with pytest.raises(ProviderError) as exc_info:
        OpenBankingProvider().list_balances(_connection())
    assert not isinstance(exc_info.value, (ProviderTransientError, ProviderAuthError))


def _entry(balance_type, amount, credit_limit_included=None):
    entry = {
        "balanceAmount": {"amount": amount, "currency": "GBP"},
        "balanceType": balance_type,
    }
    if credit_limit_included is not None:
        entry["creditLimitIncluded"] = credit_limit_included
    return entry


def test_pick_balance_prefers_booked_over_expected_and_available():
    payload = {
        "balances": [
            _entry("interimAvailable", "1"),
            _entry("expected", "2"),
            _entry("interimBooked", "3"),
        ]
    }
    assert _pick_balance(payload)["balanceType"] == "interimBooked"


def test_pick_balance_prefers_expected_over_available():
    payload = {
        "balances": [_entry("interimAvailable", "1"), _entry("expected", "2")]
    }
    assert _pick_balance(payload)["balanceType"] == "expected"


def test_pick_balance_falls_back_to_available():
    payload = {"balances": [_entry("forwardAvailable", "1"), _entry("interimAvailable", "2")]}
    assert _pick_balance(payload)["balanceType"] == "interimAvailable"


def test_pick_balance_skips_credit_limit_included():
    payload = {
        "balances": [
            _entry("closingBooked", "5000", credit_limit_included=True),
            _entry("interimAvailable", "100", credit_limit_included=False),
        ]
    }
    picked = _pick_balance(payload)
    assert picked["balanceType"] == "interimAvailable"
    assert picked["balanceAmount"]["amount"] == "100"


def test_pick_balance_unknown_type_used_when_only_option():
    payload = {"balances": [_entry("information", "7")]}
    assert _pick_balance(payload)["balanceType"] == "information"


def test_pick_balance_raises_when_only_credit_limit_included():
    payload = {"balances": [_entry("closingBooked", "5000", credit_limit_included=True)]}
    with pytest.raises(ProviderError):
        _pick_balance(payload)


def test_pick_balance_raises_when_empty():
    with pytest.raises(ProviderError):
        _pick_balance({"balances": []})


# --- ensure_access_token -------------------------------------------------


def _creds(**overrides):
    creds = {
        "access_token": "old-access",
        "refresh_token": "old-refresh",
        "requisition_id": REQUISITION_ID,
    }
    creds.update(overrides)
    return creds


def _patch_post(mocker, routes):
    """routes: {path_suffix: response_or_exception}; records called URLs."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs.get("json")))
        for suffix, outcome in routes.items():
            if url.endswith(suffix):
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise AssertionError(f"Unexpected URL: {url}")

    mocker.patch("utils.providers.open_banking.requests.post", side_effect=fake_post)
    return calls


def test_ensure_access_token_keeps_unexpired_token(mocker):
    calls = _patch_post(mocker, {})
    creds = _creds(access_expires_at=NOW + 3600)
    assert ensure_access_token(creds, "sid", "skey", now=NOW) == creds
    assert calls == []


def test_ensure_access_token_keeps_token_without_known_expiry(mocker):
    calls = _patch_post(mocker, {})
    creds = _creds()
    assert ensure_access_token(creds, now=NOW) == creds
    assert calls == []


def test_ensure_access_token_refreshes_expired_token(mocker):
    calls = _patch_post(
        mocker,
        {"/token/refresh/": _resp(200, {"access": "new-access", "access_expires": 86400})},
    )
    creds = _creds(access_expires_at=NOW - 10)
    updated = ensure_access_token(creds, "sid", "skey", now=NOW)
    assert updated["access_token"] == "new-access"
    assert updated["refresh_token"] == "old-refresh"
    assert updated["access_expires_at"] == NOW + 86400
    assert updated["requisition_id"] == REQUISITION_ID
    assert calls == [(f"{BASE}/token/refresh/", {"refresh": "old-refresh"})]
    assert creds["access_token"] == "old-access"


def test_ensure_access_token_force_refreshes(mocker):
    _patch_post(mocker, {"/token/refresh/": _resp(200, {"access": "new-access"})})
    updated = ensure_access_token(_creds(access_expires_at=NOW + 3600), force=True, now=NOW)
    assert updated["access_token"] == "new-access"


def test_ensure_access_token_falls_back_to_new_token_when_refresh_rejected(mocker):
    calls = _patch_post(
        mocker,
        {
            "/token/refresh/": _resp(401),
            "/token/new/": _resp(
                200,
                {
                    "access": "fresh-access",
                    "access_expires": 86400,
                    "refresh": "fresh-refresh",
                    "refresh_expires": 2592000,
                },
            ),
        },
    )
    updated = ensure_access_token(_creds(), "sid", "skey", force=True, now=NOW)
    assert updated["access_token"] == "fresh-access"
    assert updated["refresh_token"] == "fresh-refresh"
    assert updated["refresh_expires_at"] == NOW + 2592000
    assert calls[-1] == (f"{BASE}/token/new/", {"secret_id": "sid", "secret_key": "skey"})


def test_ensure_access_token_skips_expired_refresh_token(mocker):
    calls = _patch_post(mocker, {"/token/new/": _resp(200, {"access": "fresh-access"})})
    creds = _creds(access_expires_at=NOW - 10, refresh_expires_at=NOW - 10)
    updated = ensure_access_token(creds, "sid", "skey", now=NOW)
    assert updated["access_token"] == "fresh-access"
    assert [url for url, _ in calls] == [f"{BASE}/token/new/"]


def test_ensure_access_token_auth_error_when_refresh_rejected_and_no_secrets(mocker):
    _patch_post(mocker, {"/token/refresh/": _resp(401)})
    with pytest.raises(ProviderAuthError):
        ensure_access_token(_creds(), force=True, now=NOW)


def test_ensure_access_token_auth_error_when_nothing_to_refresh_with(mocker):
    _patch_post(mocker, {})
    with pytest.raises(ProviderAuthError):
        ensure_access_token(_creds(access_token=None, refresh_token=None), now=NOW)


def test_ensure_access_token_transient_when_all_failures_transient(mocker):
    _patch_post(mocker, {"/token/refresh/": _resp(503)})
    with pytest.raises(ProviderTransientError):
        ensure_access_token(_creds(), force=True, now=NOW)


def test_ensure_access_token_auth_error_when_new_token_rejected(mocker):
    _patch_post(mocker, {"/token/refresh/": _resp(503), "/token/new/": _resp(401)})
    with pytest.raises(ProviderAuthError):
        ensure_access_token(_creds(), "sid", "bad", force=True, now=NOW)


def test_ensure_access_token_uses_stored_base_url(mocker):
    calls = _patch_post(mocker, {"/token/refresh/": _resp(200, {"access": "a"})})
    ensure_access_token(
        _creds(base_url="https://sandbox.example/api/v2/"), force=True, now=NOW
    )
    assert calls[0][0] == "https://sandbox.example/api/v2/token/refresh/"
