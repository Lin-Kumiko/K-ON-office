"""Test fixtures.

* A template SQLite database is built once per session by running the real Alembic
  migrations and the base seed; every test gets its own copy (full isolation, fast).
* The business clock is frozen at FIXED_NOW (a Monday) so date rules are reproducible.
* Passwords are generated per session; nothing is written to the development database.
"""
from __future__ import annotations

import secrets
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core import timeutil
from app.core.config import BACKEND_DIR, load_settings
from app.core.db import Database
from app.main import create_app
from app.seed import seed_base

FIXED_NOW = "2026-10-19T10:00:00"
TEST_PASSWORD = f"Tea{secrets.token_hex(4)}9"
ITERATIONS = 1000


def _url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def migrate(db_path: Path) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.cmd_opts = type("o", (), {"x": [f"url={_url(db_path)}"]})()
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def template_db(tmp_path_factory) -> Path:
    timeutil.set_fixed_now(datetime.fromisoformat(FIXED_NOW))
    path = tmp_path_factory.mktemp("template") / "template.sqlite3"
    migrate(path)
    db = Database(_url(path))
    with db.session(write=True) as s:
        seed_base(s, TEST_PASSWORD, ITERATIONS)
        s.commit()
    db.dispose()
    return path


def make_settings(data_dir: Path, db_path: Path):
    return load_settings(env="test", data_dir=data_dir, database_url=_url(db_path), password_iterations=ITERATIONS,
                         fixed_now=FIXED_NOW, frontend_dist=data_dir / "no-dist")


@pytest.fixture()
def db_path(template_db, tmp_path) -> Path:
    p = tmp_path / "test.sqlite3"
    shutil.copy(template_db, p)
    return p


@pytest.fixture()
def app(db_path, tmp_path):
    application = create_app(make_settings(tmp_path / "data", db_path))
    yield application
    application.state.db.dispose()


class Api:
    """Thin authenticated wrapper over TestClient / httpx.Client."""

    def __init__(self, client, token: str | None = None):
        self.client = client
        self.token = token

    def _h(self, extra=None):
        h = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        h.update(extra or {})
        return h

    def get(self, url, **kw):
        return self.client.get(url, headers=self._h(kw.pop("headers", None)), **kw)

    def post(self, url, json=None, **kw):
        return self.client.post(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def put(self, url, json=None, **kw):
        return self.client.put(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def delete(self, url, **kw):
        return self.client.delete(url, headers=self._h(kw.pop("headers", None)), **kw)


def login(client, username: str, password: str = TEST_PASSWORD) -> Api:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"login {username} failed: {r.status_code} {r.text[:200]}"
    return Api(client, r.json()["token"])


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def as_user(client):
    cache: dict[str, Api] = {}

    def _get(username: str) -> Api:
        if username not in cache:
            cache[username] = login(client, username)
        return cache[username]
    return _get


@pytest.fixture()
def sql(app):
    """Read-only helper for asserting the final database state."""
    def _q(statement: str, **params):
        with app.state.db.engine.connect() as conn:
            return conn.exec_driver_sql(statement, tuple(params.values()) if params else ()).fetchall()
    return _q


def ok(resp, status: int = 200):
    assert resp.status_code == status, f"expected {status}, got {resp.status_code}: {resp.text[:500]}"
    return resp.json()


def err(resp, status: int, code: str | None = None):
    assert resp.status_code == status, f"expected {status}, got {resp.status_code}: {resp.text[:500]}"
    body = resp.json()
    assert "error" in body and {"code", "message"} <= set(body["error"]), body
    if code:
        assert body["error"]["code"] == code, body
    return body
