import pytest

from biothings_pulse.checker.loader import (
    UnsupportedPlugin,
    build_manifest_dumper,
)
from biothings_pulse.plugins.models import PluginRef


def _ref(fixture_repo, name):
    plugin_dir = fixture_repo / "plugins" / name
    return PluginRef(
        repo="testrepo",
        name=name,
        plugin_type="manifest",
        path=plugin_dir,
        manifest_path=plugin_dir / "manifest.json",
    )


def test_manifest_with_release_func(fixture_repo, tmp_path):
    dumper = build_manifest_dumper(_ref(fixture_repo, "acme"), tmp_path)
    # data_url list -> SRC_URLS list, LastModified HTTP base.
    assert dumper.SRC_URLS == [
        "http://example.com/acme_a.tsv",
        "http://example.com/acme_b.tsv",
    ]
    assert "LastModifiedHTTPDumper" in [c.__name__ for c in type(dumper).__mro__]
    # The custom release function (version:get_release) drives set_release().
    dumper.set_release()
    assert dumper.release == "2024-07-01"


def test_manifest_without_release_func(fixture_repo, tmp_path):
    dumper = build_manifest_dumper(_ref(fixture_repo, "basic"), tmp_path)
    assert dumper.SRC_URLS == ["http://example.com/basic.txt"]
    assert dumper.SRC_NAME == "basic"


def test_release_from_shared_repo_module(fixture_repo, tmp_path):
    # release = "hub.dataload.shared_release:get_release" lives at the repo root,
    # not in the plugin dir, and reads the manifest __metadata__ (DogPark-style).
    plugin_dir = fixture_repo / "plugins" / "shared"
    ref = PluginRef(
        repo="testrepo",
        name="shared",
        plugin_type="manifest",
        path=plugin_dir,
        manifest_path=plugin_dir / "manifest.json",
        repo_path=fixture_repo,
    )
    dumper = build_manifest_dumper(ref, tmp_path)
    assert type(dumper).__metadata__ == {"version": "2024-shared"}
    dumper.set_release()
    assert dumper.release == "2024-shared"


def test_shared_release_module_is_purged_after_load(fixture_repo, tmp_path):
    # Loading a shared release module (hub.dataload.shared_release) must not leave
    # the repo-local 'hub' package cached, or another repo's `import hub.*` would
    # resolve against it (the DogPark cross-repo collision).
    import sys

    for m in [k for k in sys.modules if k == "hub" or k.startswith("hub.")]:
        sys.modules.pop(m, None)
    plugin_dir = fixture_repo / "plugins" / "shared"
    ref = PluginRef(
        repo="testrepo",
        name="shared",
        plugin_type="manifest",
        path=plugin_dir,
        manifest_path=plugin_dir / "manifest.json",
        repo_path=fixture_repo,
    )
    dumper = build_manifest_dumper(ref, tmp_path)
    dumper.set_release()
    assert dumper.release == "2024-shared"
    assert "hub" not in sys.modules
    assert "hub.dataload.shared_release" not in sys.modules


def test_upload_only_is_unsupported(fixture_repo, tmp_path):
    with pytest.raises(UnsupportedPlugin):
        build_manifest_dumper(_ref(fixture_repo, "uploadonly"), tmp_path)
