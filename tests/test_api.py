import pytest
from fastapi.testclient import TestClient

from biothings_pulse.checker.models import CheckResult
from biothings_pulse.config import Settings
from biothings_pulse.main import create_app
from biothings_pulse.plugins.models import PluginRef


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Canned check result so the API tests need no network / SDK.
    def fake_check(ref, settings):
        return CheckResult(
            status="ok",
            latest_version="2024-10",
            download_urls=["http://example.com/f.tsv"],
        )

    monkeypatch.setattr("biothings_pulse.service.check_plugin", fake_check)

    settings = Settings(
        sync_on_startup=False,
        scheduler_enabled=False,
        store_backend="sqlite",
        sqlite_path=tmp_path / "state.db",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        # Manually populate the catalog (no git sync in tests).
        c.app.state.service._catalog["myrepo/mysrc"] = PluginRef(
            repo="myrepo", name="mysrc", plugin_type="manifest", path=tmp_path
        )
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["catalog_size"] == 1


def test_catalog(client):
    resp = client.get("/catalog")
    assert resp.status_code == 200
    assert resp.json()["sources"][0]["plugin"] == "mysrc"


def test_dashboard_landing_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "BioThings Pulse" in body
    assert 'href="/docs"' in body  # links to the API docs


def test_check_then_status_and_acknowledge(client):
    # Force a check -> baseline set, no update.
    resp = client.post("/sources/myrepo/mysrc/check")
    assert resp.status_code == 200
    body = resp.json()
    assert body["latest_version"] == "2024-10"
    assert body["current_version"] == "2024-10"
    assert body["has_update"] is False
    assert body["download_urls"] == ["http://example.com/f.tsv"]

    # Cached read.
    assert client.get("/sources/myrepo/mysrc").json()["latest_version"] == "2024-10"

    # Acknowledge is idempotent here (already baselined).
    assert client.post("/sources/myrepo/mysrc/acknowledge").status_code == 200


def test_unknown_source_404(client):
    assert client.get("/sources/nope/nope").status_code == 404
    assert client.post("/sources/nope/nope/check").status_code == 404


def test_refresh_all(client):
    resp = client.post("/admin/refresh")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
