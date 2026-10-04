import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from utils.providers.base import ProviderAuthError, ProviderError, ProviderTransientError
from utils.providers.trading212 import Trading212Provider

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "t212_account_summary.json").read_text()
)


def test_list_balances_uses_total_value(mocker):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = FIXTURE
    mocker.patch("utils.providers.trading212.requests.get", return_value=resp)

    provider = Trading212Provider()
    balances = provider.list_balances(
        {
            "credentials": {
                "api_key": "k",
                "api_secret": "s",
                "base_url": "https://live.trading212.com/api/v0",
            }
        }
    )
    assert len(balances) == 1
    assert balances[0].external_account_id == "12345678"
    assert balances[0].currency == "GBP"
    assert balances[0].amount == Decimal("15432.5")
    assert "Trading 212" in balances[0].name


def test_401_raises_auth_error(mocker):
    resp = MagicMock()
    resp.status_code = 401
    resp.text = "Bad API key"
    mocker.patch("utils.providers.trading212.requests.get", return_value=resp)
    with pytest.raises(ProviderAuthError):
        Trading212Provider().list_balances(
            {"credentials": {"api_key": "k", "api_secret": "s"}}
        )


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_rate_limit_and_server_errors_are_transient(mocker, status_code):
    resp = MagicMock()
    resp.status_code = status_code
    mocker.patch("utils.providers.trading212.requests.get", return_value=resp)
    with pytest.raises(ProviderTransientError):
        Trading212Provider().list_balances(
            {"credentials": {"api_key": "k", "api_secret": "s"}}
        )


def test_timeout_is_transient(mocker):
    mocker.patch(
        "utils.providers.trading212.requests.get",
        side_effect=requests.Timeout("slow"),
    )
    with pytest.raises(ProviderTransientError):
        Trading212Provider().list_balances(
            {"credentials": {"api_key": "k", "api_secret": "s"}}
        )


def test_client_error_is_not_transient(mocker):
    resp = MagicMock()
    resp.status_code = 404
    mocker.patch("utils.providers.trading212.requests.get", return_value=resp)
    with pytest.raises(ProviderError) as exc_info:
        Trading212Provider().list_balances(
            {"credentials": {"api_key": "k", "api_secret": "s"}}
        )
    assert not isinstance(exc_info.value, ProviderTransientError)
