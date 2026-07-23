from biothings_pulse.store.sqlite_store import SQLiteStateStore


def make_store(tmp_path):
    return SQLiteStateStore(tmp_path / "state.db")


def test_roundtrip_and_baseline(tmp_path):
    store = make_store(tmp_path)

    # First check establishes a baseline -> not "has_update".
    state = store.record_check(
        "repoA", "src1", "manifest", latest_version="2024-01", download_urls=["u"]
    )
    assert state.current_version == "2024-01"
    assert state.latest_version == "2024-01"
    assert state.has_update is False
    assert state.status == "ok"

    # A newer remote version now reads as an available update.
    state = store.record_check(
        "repoA", "src1", "manifest", latest_version="2024-06", download_urls=["u"]
    )
    assert state.current_version == "2024-01"  # baseline unchanged
    assert state.latest_version == "2024-06"
    assert state.has_update is True

    # Acknowledge advances the baseline.
    state = store.acknowledge("repoA", "src1")
    assert state.current_version == "2024-06"
    assert state.has_update is False


def test_error_status_preserves_current(tmp_path):
    store = make_store(tmp_path)
    store.record_check("r", "s", "manifest", latest_version="1")
    state = store.record_check(
        "r", "s", "manifest", latest_version=None, status="error", error="boom"
    )
    assert state.status == "error"
    assert state.error == "boom"
    assert state.current_version == "1"  # not clobbered on error


def test_list_all(tmp_path):
    store = make_store(tmp_path)
    store.record_check("r", "a", "manifest", latest_version="1")
    store.record_check("r", "b", "advanced", latest_version="2")
    keys = {s.key for s in store.list_all()}
    assert keys == {"r/a", "r/b"}


def test_persistence_across_instances(tmp_path):
    store = make_store(tmp_path)
    store.record_check("r", "a", "manifest", latest_version="1")
    store.close()
    reopened = make_store(tmp_path)
    assert reopened.get("r", "a").latest_version == "1"
