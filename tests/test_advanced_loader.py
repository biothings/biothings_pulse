"""Advanced-plugin loading: load the dumper directly, bypassing __init__."""

from biothings_pulse.checker.loader import load_advanced_dumper
from biothings_pulse.plugins.models import PluginRef


def _adv_ref(fixture_repo, name):
    return PluginRef(
        repo="testrepo",
        name=name,
        plugin_type="advanced",
        path=fixture_repo / "acmepkg" / "hub" / "dataload" / "sources" / name,
    )


def test_loads_dumper_despite_broken_package_init(fixture_repo, tmp_path):
    # The 'broken' plugin's __init__.py imports a missing module (simulating an
    # uploader/key-lookup that needs a full Hub). The loader must still return
    # the dumper by loading dumper.py directly.
    dumper = load_advanced_dumper(_adv_ref(fixture_repo, "broken"), tmp_path)
    assert dumper.SRC_NAME == "broken"
    assert type(dumper).__name__ == "BrokenDumper"


def test_loads_clean_advanced_dumper(fixture_repo, tmp_path):
    dumper = load_advanced_dumper(_adv_ref(fixture_repo, "widget"), tmp_path)
    assert dumper.SRC_NAME == "widget"
