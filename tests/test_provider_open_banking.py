import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from utils.providers.base import ProviderAuthError
from utils.providers.open_banking import OpenBankingProvider

BALANCES_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "gocardless_balances.json").read_text()
)
DETAILS_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "gocardless_account_details.json").read_text()
)

ACCOUNT_ID = "acc-uuid-1111"
REQUISITION_ID = "req-abc-123"
BASE = "https://bankaccountdata.gocardless.com/api/v2"


def _connection():
    return {
        "credentials": {
            "access_token": "access-tok",
            "refresh_token": "refresh-tok",
            "requisition_id": REQUISITION_ID,
        }
    }


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
    assert balances[0].amount == Decimal("1250.55")
    assert balances[0].name == "Main Current"


def test_401_raises_auth_error(mocker):
    resp = MagicMock()
    resp.status_code = 401
    resp.text = "Unauthorized"
    mocker.patch("utils.providers.open_banking.requests.get", return_value=resp)

    with pytest.raises(ProviderAuthError):
        OpenBankingProvider().list_balances(_connection())
