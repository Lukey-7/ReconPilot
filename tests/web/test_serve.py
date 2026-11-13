"""Serving the built front end from the API, and starting Vite in development."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reconpilot_web import cli
from reconpilot_web.app import create_app

INDEX = "<!doctype html><title>ReconPilot</title><div id=root></div>"


@pytest.fixture
def dist(tmp_path):
    folder = tmp_path / "web" / "dist"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text(INDEX, encoding="utf-8")
    (folder / "assets" / "index-abc123.js").write_text("console.log('rp')", encoding="utf-8")
    (folder / "theme-init.js").write_text("// theme", encoding="utf-8")
    (tmp_path / "web" / "secret.txt").write_text("not served", encoding="utf-8")
    return folder


@pytest.fixture
def web_client(clean_db, settings, dist):
    application = create_app(settings, web_dist=dist)
    with TestClient(application) as c:
        yield c
    application.state.engine.dispose()


def test_pages_get_index_html_with_security_headers(web_client):
    for path in ("/", "/overview", "/cases", "/signoff", "/signin"):
        response = web_client.get(path)
        assert response.status_code == 200, path
        assert response.text == INDEX
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["Content-Security-Policy"] == "default-src 'self'; frame-ancestors 'none'"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Cache-Control"] == "no-cache"
    assert web_client.head("/cases").status_code == 200


def test_files_are_served_and_assets_cached(web_client):
    response = web_client.get("/assets/index-abc123.js")
    assert response.status_code == 200 and response.text == "console.log('rp')"
    assert "immutable" in response.headers["Cache-Control"]
    assert web_client.get("/theme-init.js").headers["Cache-Control"] == "no-cache"
    assert web_client.get("/assets/missing.js").status_code == 404


def test_api_routes_win_and_unknown_api_paths_stay_404(web_client):
    assert web_client.get("/api/auth/me").status_code == 401
    response = web_client.get("/api/no-such-route")
    assert response.status_code == 404 and response.json() == {"detail": "Not Found"}


def test_nothing_outside_dist_is_served(web_client):
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt"):
        response = web_client.get(path)
        assert "not served" not in response.text, path


def test_without_a_build_only_the_api_is_served(clean_db, settings):
    application = create_app(settings)
    with TestClient(application) as c:
        assert c.get("/").status_code == 404
        assert c.get("/api/auth/me").status_code == 401
    application.state.engine.dispose()


def test_web_dist_found_only_once_built(tmp_path, dist):
    assert cli.web_dist(tmp_path / "web") == dist
    assert cli.web_dist(tmp_path / "elsewhere") is None


def test_vite_starts_only_when_installed(tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    assert cli.vite_command(web) is None and cli.start_vite(web) is None  # npm install not run yet

    script = web / "node_modules" / "vite" / "bin" / "vite.js"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name == "node" else None)
    assert cli.vite_command(web) == ["/usr/bin/node", str(script)]

    monkeypatch.setattr("shutil.which", lambda name: None)  # Node not installed
    assert cli.vite_command(web) is None


def test_stop_process_ignores_a_missing_or_finished_process():
    class Finished:
        def poll(self):
            return 0

        def terminate(self):  # pragma: no cover - must not be called
            raise AssertionError("terminated a finished process")

    cli.stop_process(None)
    cli.stop_process(Finished())
