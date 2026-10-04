from datetime import datetime, timezone

import pytest

from utils.sync import month_end
from utils.sync.dates import previous_month_end

ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_KEY": "service",
    "SYNC_CREDENTIALS_KEY": "key",
}


class FakeDb:
    def __init__(self, user_ids=None, error=None):
        self.user_ids = user_ids or []
        self.error = error

    def list_user_ids_for_scheduled_sync(self):
        if self.error:
            raise self.error
        return list(self.user_ids)


@pytest.fixture
def env(monkeypatch):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GOCARDLESS_SECRET_ID", "sid")
    monkeypatch.setenv("GOCARDLESS_SECRET_KEY", "skey")


def _setup(mocker, db, results):
    """results: {user_id: result dict or Exception}."""
    mocker.patch.object(month_end.SupabaseHandler, "from_env", return_value=db)
    calls = []

    def fake_run_sync(db_arg, user_id, as_of, trigger, **kwargs):
        calls.append((user_id, as_of, trigger, kwargs))
        outcome = results[user_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    mocker.patch.object(month_end, "run_sync", side_effect=fake_run_sync)
    return calls


def ok(**overrides):
    return {"status": "success", "error_count": 0, **overrides}


def test_missing_required_env_exits_1(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    assert month_end.main() == 1


def test_all_success_exits_0_and_runs_scheduled_previous_month_end(env, mocker):
    calls = _setup(mocker, FakeDb(["u1", "u2"]), {"u1": ok(), "u2": ok()})
    assert month_end.main() == 0
    assert [c[0] for c in calls] == ["u1", "u2"]
    assert all(c[2] == "scheduled" for c in calls)
    expected = previous_month_end(datetime.now(timezone.utc).date())
    assert all(c[1] == expected for c in calls)


def test_gocardless_secrets_passed_to_refreshers(env, mocker):
    calls = _setup(mocker, FakeDb(["u1"]), {"u1": ok()})
    factory = mocker.patch.object(
        month_end, "default_credential_refreshers", return_value={"open_banking": object()}
    )
    assert month_end.main() == 0
    factory.assert_called_once_with("sid", "skey")
    assert calls[0][3]["credential_refreshers"] is factory.return_value


@pytest.mark.parametrize(
    "result",
    [
        {"status": "partial", "error_count": 1},
        {"status": "failed", "error_count": 2},
        {"status": "success", "error_count": 1},
        {},
    ],
)
def test_non_clean_run_exits_1(env, mocker, result):
    _setup(mocker, FakeDb(["u1", "u2"]), {"u1": result, "u2": ok()})
    assert month_end.main() == 1


def test_one_user_exception_does_not_skip_others(env, mocker, caplog):
    calls = _setup(
        mocker,
        FakeDb(["u1", "u2"]),
        {"u1": RuntimeError("postgres://user:pw@host"), "u2": ok()},
    )
    assert month_end.main() == 1
    assert [c[0] for c in calls] == ["u1", "u2"]
    assert "pw@host" not in caplog.text


def test_user_list_failure_exits_1(env, mocker):
    calls = _setup(mocker, FakeDb(error=RuntimeError("db down")), {})
    assert month_end.main() == 1
    assert calls == []


def test_no_users_exits_0(env, mocker):
    _setup(mocker, FakeDb([]), {})
    assert month_end.main() == 0
