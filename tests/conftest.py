"""Shared fixtures: the two hand-built miniatures, a fake engine and a fake HTTP response."""

import io
import json
import pathlib
import urllib.error

import pytest

from etl import market as market_layer
from tests import bank_fixture, market_fixture

ROOT = pathlib.Path(__file__).resolve().parent.parent


class FakeEngine:
    """Stands in for etl.helpers.Engine: records every statement and answers from a script.

    answers: [(substring, rows or callable(cypher) -> rows)] — the first entry whose substring occurs in the
    statement answers it; anything unscripted returns no rows."""

    def __init__(self, answers=None, graph="t", tenants=()):
        self.graph, self.answers = graph, list(answers or [])
        self.queries, self.posts, self.tenant_ids, self.calls = [], [], list(tenants), 0

    def q(self, cypher):
        self.calls += 1
        self.queries.append(cypher)
        for key, rows in self.answers:
            if key in cypher:
                return rows(cypher) if callable(rows) else rows
        return []

    def post(self, path, body, **kw):
        self.posts.append((path, body, kw))
        return {"ok": True}

    def tenants(self):
        return self.tenant_ids

    def create_tenant(self, quotas=None):
        self.tenant_ids.append(self.graph)

    def export_snapshot(self, dest):
        dest.write_bytes(b"snap")
        return 4


class FakeResponse(io.BytesIO):
    """A urlopen() result: a readable, closable body."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def http_error(url, code=500, body=b"boom"):
    """An HTTPError as urllib raises it."""
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(body))


def json_body(obj) -> FakeResponse:
    """A FakeResponse carrying obj as JSON."""
    return FakeResponse(json.dumps(obj).encode())


@pytest.fixture
def fake_engine():
    return FakeEngine


@pytest.fixture(scope="module")
def market_dir(tmp_path_factory):
    return market_fixture.write_fixture(tmp_path_factory.mktemp("market"))


@pytest.fixture(scope="module")
def market(market_dir):
    return market_layer.build(market_dir)


@pytest.fixture(scope="module")
def bank_dir(tmp_path_factory):
    d = bank_fixture.write_fixture(tmp_path_factory.mktemp("bank"))
    (d / "validation_report_v1.json").write_text(json.dumps({"ok": True}))
    return d
