import pytest
from fastapi.testclient import TestClient

from biothings_pulse.checker.models import CheckResult
from biothings_pulse.config import Settings
from biothings_pulse.main import create_app
from biothings_pulse.plugins.models import PluginRef

ADMIN = {"Authorization": "Bearer test-token"}


def _fake_check(ref, settings):
    return CheckResult(
        status="ok",
        latest_version="2024-10",
        download_urls=["http://example.com/f.tsv"],
        schedule="0 2 * * 0",
    )


def _make_client(tmp_path, monkeypatch, **overrides):
    monkeypatch.setattr("biothings_pulse.service.check_plugin", _fake_check)
    settings = Settings(
        sync_on_startup=False,
        scheduler_enabled=False,
        store_backend="sqlite",
        sqlite_path=tmp_path / "state.db",
        **overrides,
    )
    app = create_app(settings)
    c = TestClient(app)
    c.__enter__()
    c.app.state.service._catalog["myrepo/mysrc"] = PluginRef(
        repo="myrepo", name="mysrc", plugin_type="manifest", path=tmp_path
    )
    return c


@pytest.fixture
def client(tmp_path, monkeypatch):
    c = _make_client(tmp_path, monkeypatch, admin_token="test-token")
    yield c
    c.__exit__(None, None, None)


def test_health(client):
    body = client.get("/health").json()
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


def test_check_records_current_version(client):
    resp = client.post("/sources/myrepo/mysrc/check", headers=ADMIN)
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_version"] == "2024-10"
    assert body["current_version_at"] is not None
    assert body["last_version"] is None
    assert body["download_urls"] == ["http://example.com/f.tsv"]
    assert body["schedule"] == "0 2 * * 0"
    assert body["next_check_at"] is not None  # computed from schedule + checked_at
    assert "has_update" not in body  # Pulse no longer owns update state

    # A cached read returns the same, without re-checking.
    assert client.get("/sources/myrepo/mysrc").json()["current_version"] == "2024-10"


def test_get_returns_pending_without_checking(client):
    body = client.get("/sources/myrepo/mysrc").json()
    assert body["status"] == "pending"
    assert body["current_version"] is None


def test_acknowledge_endpoint_removed(client):
    assert client.post("/sources/myrepo/mysrc/acknowledge").status_code == 404


def test_unknown_source_404(client):
    assert client.get("/sources/nope/nope").status_code == 404
    assert client.post("/sources/nope/nope/check", headers=ADMIN).status_code == 404


def test_refresh_all(client):
    resp = client.post("/admin/refresh", headers=ADMIN)
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_run_due_checks_respects_schedule(client):
    svc = client.app.state.service
    assert svc.run_due_checks() == 1
    assert svc.run_due_checks() == 0


# -- admin security -------------------------------------------------------

def test_reads_are_public(client):
    for path in ("/health", "/catalog", "/sources", "/sources/myrepo/mysrc"):
        assert client.get(path).status_code == 200  # no token needed


def test_admin_requires_valid_token(client):
    assert client.post("/admin/refresh").status_code == 401  # missing
    assert (
        client.post("/admin/refresh", headers={"Authorization": "Bearer nope"}).status_code
        == 401  # wrong
    )
    assert client.post("/admin/refresh", headers=ADMIN).status_code == 200
    # X-Admin-Token header is also accepted (use refresh; sync would rebuild the
    # injected test catalog via a real git sync)
    assert (
        client.post("/admin/refresh", headers={"X-Admin-Token": "test-token"}).status_code
        == 200
    )
    # ?refresh=true is admin-gated too
    assert client.get("/sources/myrepo/mysrc?refresh=true").status_code == 401
    assert (
        client.get("/sources/myrepo/mysrc?refresh=true", headers=ADMIN).status_code == 200
    )


def test_admin_disabled_when_no_token(tmp_path, monkeypatch):
    c = _make_client(tmp_path, monkeypatch, admin_token=None)
    try:
        assert c.get("/health").status_code == 200  # reads still work
        assert c.post("/admin/refresh").status_code == 403
        assert c.post("/admin/refresh", headers=ADMIN).status_code == 403  # still off
        assert c.post("/sources/myrepo/mysrc/check").status_code == 403
    finally:
        c.__exit__(None, None, None)
