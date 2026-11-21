"""Static serving of the built front end: cache policy per file kind, and HEAD support."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_settings
from app.main import create_app
from tests.conftest import FIXED_NOW, ITERATIONS, _url

ASSET = "/assets/index-abc123.js"


@pytest.fixture()
def spa_client(db_path, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "release.txt").write_text("deadbeef\n", encoding="utf-8")
    (dist / "teacup.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    settings = load_settings(env="test", data_dir=tmp_path / "data", database_url=_url(db_path),
                             password_iterations=ITERATIONS, fixed_now=FIXED_NOW, frontend_dist=dist)
    application = create_app(settings)
    with TestClient(application) as c:
        yield c
    application.state.db.dispose()


def test_hashed_assets_are_cached_for_a_year(spa_client):
    r = spa_client.get(ASSET)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_not_modified_response_keeps_the_cache_header(spa_client):
    etag = spa_client.get(ASSET).headers["etag"]
    r = spa_client.get(ASSET, headers={"If-None-Match": etag})
    assert r.status_code == 304
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_page_shell_is_always_revalidated(spa_client):
    for path in ("/", "/dashboard", "/approvals/12"):
        r = spa_client.get(path)
        assert r.status_code == 200, path
        assert r.headers["cache-control"] == "no-cache", path
        assert "<title>t</title>" in r.text


def test_release_marker_is_never_cached(spa_client):
    r = spa_client.get("/release.txt")
    assert r.status_code == 200
    assert r.text.strip() == "deadbeef"
    assert r.headers["cache-control"] == "no-cache"


def test_other_root_files_are_cached_for_a_day(spa_client):
    r = spa_client.get("/teacup.svg")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=86400"


@pytest.mark.parametrize("path", ["/", "/dashboard", "/api/health", ASSET, "/release.txt", "/teacup.svg"])
def test_head_requests_work_and_have_no_body(spa_client, path):
    r = spa_client.head(path)
    assert r.status_code == 200, path
    assert r.content == b""


def test_head_on_unknown_api_path_is_not_found(spa_client):
    assert spa_client.head("/api/does-not-exist").status_code == 404
    assert spa_client.get("/api/does-not-exist").status_code == 404
