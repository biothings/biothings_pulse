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


def test_upload_only_is_unsupported(fixture_repo, tmp_path):
    with pytest.raises(UnsupportedPlugin):
        build_manifest_dumper(_ref(fixture_repo, "uploadonly"), tmp_path)
