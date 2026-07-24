from biothings_pulse.store.sqlite_store import SQLiteStateStore


def make_store(tmp_path):
    return SQLiteStateStore(tmp_path / "state.db")


def test_first_sighting_sets_current(tmp_path):
    store = make_store(tmp_path)
    st = store.record_check(
        "r", "s", "manifest", detected_version="1", download_urls=["u"]
    )
    assert st.current_version == "1"
    assert st.current_version_at is not None
    assert st.last_version is None
    assert st.last_version_at is None
    assert st.status == "ok"
    assert st.checked_at is not None


def test_unchanged_preserves_first_seen(tmp_path):
    store = make_store(tmp_path)
    first = store.record_check("r", "s", "manifest", detected_version="1")
    again = store.record_check("r", "s", "manifest", detected_version="1")
    assert again.current_version == "1"
    assert again.current_version_at == first.current_version_at  # first-seen kept
    assert again.last_version is None


def test_new_version_rotates_to_last(tmp_path):
    store = make_store(tmp_path)
    first = store.record_check("r", "s", "manifest", detected_version="1")
    updated = store.record_check("r", "s", "manifest", detected_version="2")
    assert updated.current_version == "2"
    assert updated.last_version == "1"
    assert updated.last_version_at == first.current_version_at
    assert updated.current_version_at >= first.current_version_at


def test_error_preserves_current_but_records_attempt(tmp_path):
    store = make_store(tmp_path)
    store.record_check("r", "s", "manifest", detected_version="1")
    st = store.record_check(
        "r", "s", "manifest", detected_version=None, status="error", error="boom"
    )
    assert st.status == "error"
    assert st.error == "boom"
    assert st.current_version == "1"  # not clobbered on error
    assert st.checked_at is not None  # attempt time recorded even on failure


def test_schedule_recorded_and_kept_on_error(tmp_path):
    store = make_store(tmp_path)
    st = store.record_check(
        "r", "s", "manifest", detected_version="1", schedule="0 2 * * 0"
    )
    assert st.schedule == "0 2 * * 0"
    # A later error keeps the previously-known schedule.
    st2 = store.record_check(
        "r", "s", "manifest", detected_version=None, status="error", error="x"
    )
    assert st2.schedule == "0 2 * * 0"


def test_download_urls_coerced_to_str(tmp_path):
    # Some dumpers (e.g. civic) put ints in to_dump; they must be stored as str
    # so the record round-trips through the List[str] model.
    store = make_store(tmp_path)
    st = store.record_check(
        "r", "s", "manifest", detected_version="1", download_urls=[1, 2, "u"]
    )
    assert st.download_urls == ["1", "2", "u"]
    assert store.get("r", "s").download_urls == ["1", "2", "u"]  # round-trips


def test_list_all_skips_corrupt_record(tmp_path):
    import json

    store = make_store(tmp_path)
    store.record_check("r", "good", "manifest", detected_version="1")
    # Inject a record that no longer validates (int download_urls).
    store._conn.execute(
        "INSERT INTO source_state (repo, plugin, doc) VALUES (?, ?, ?)",
        ("r", "bad", json.dumps({"repo": "r", "plugin": "bad", "download_urls": [1, 2]})),
    )
    store._conn.commit()
    keys = {s.key for s in store.list_all()}
    assert "r/good" in keys and "r/bad" not in keys  # corrupt row skipped, not fatal


def test_list_all_and_persistence(tmp_path):
    store = make_store(tmp_path)
    store.record_check("r", "a", "manifest", detected_version="1")
    store.record_check("r", "b", "advanced", detected_version="2")
    assert {s.key for s in store.list_all()} == {"r/a", "r/b"}
    store.close()
    reopened = make_store(tmp_path)
    assert reopened.get("r", "a").current_version == "1"
