"""Shared pytest fixtures."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest


class FakeSupabaseQuery:
    """Chainable mock for the supabase-py builder API.

    Records the operation chain so tests can assert on it, then returns a
    canned response payload from `.execute()`.
    """

    def __init__(self, response_data=None):
        self._response_data = response_data if response_data is not None else []
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self
        return _record

    def execute(self):
        self.calls.append(("execute", (), {}))
        resp = MagicMock()
        resp.data = self._response_data
        return resp


@pytest.fixture
def fake_supabase(mocker):
    """A MagicMock standing in for the supabase client.

    Returns a callable `set_table(name, response_data)` so each test can wire
    the rows that `.table(name)...execute()` should return.
    """
    client = MagicMock()
    tables: dict[str, FakeSupabaseQuery] = {}

    def set_table(name: str, response_data):
        tables[name] = FakeSupabaseQuery(response_data)
        return tables[name]

    def _table(name):
        return tables.setdefault(name, FakeSupabaseQuery([]))

    client.table.side_effect = _table
    client.set_table = set_table
    client._tables = tables
    return client


@pytest.fixture
def sample_user_id():
    return "google-sub-abc123"


@pytest.fixture
def sample_today():
    return date(2026, 5, 15)
