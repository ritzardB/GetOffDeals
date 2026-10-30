"""Core validation and security helpers for GetOffDeals invitations."""

import csv
import hashlib
import io
import re
import secrets
from datetime import datetime, timezone
import getoffdeals.invitation_schema as schema_module


def test_schema_initializer_executes_sql(monkeypatch):
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            captured["query"] = query
            captured["params"] = params

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        schema_module,
        "get_connection",
        lambda: FakeConnection(),
    )

    schema_module.ensure_invitation_schema()

    query = captured["query"]
    assert "public.invitation_contacts" in query
    assert "public.invitation_campaigns" in query
    assert "public.invitation_messages" in query
    assert "public.invitation_unsubscribes" in query
    assert "consent_evidence" in query
    assert "token_hash TEXT NOT NULL UNIQUE" in query
