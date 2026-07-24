from biothings_pulse.checker.runner import check_plugin, run_dumper_check
from biothings_pulse.config import get_settings
from biothings_pulse.plugins.models import PluginRef


class FakeDumper:
    """Stand-in exercising run_dumper_check without the SDK/network."""

    def __init__(self, release=None, urls=(), raise_exc=None):
        self.src_name = "fake"
        self.release = None
        self._release_to_set = release
        self._urls = list(urls)
        self._raise = raise_exc
        self.to_dump = []
        self._state = {"client": None}

    def create_todump_list(self, force=False):
        if self._raise:
            raise self._raise
        self.release = self._release_to_set
        self.to_dump = [{"remote": u, "local": "/tmp/x"} for u in self._urls]

    def release_client(self):
        pass


def test_run_dumper_check_ok():
    result = run_dumper_check(
        FakeDumper(release="2024-09", urls=["http://a", "http://b"])
    )
    assert result.status == "ok"
    assert result.latest_version == "2024-09"
    assert result.download_urls == ["http://a", "http://b"]


def test_run_dumper_check_error():
    result = run_dumper_check(FakeDumper(raise_exc=RuntimeError("network down")))
    assert result.status == "error"
    assert "network down" in result.error


def test_run_dumper_check_empty_is_unsupported():
    # No release and no URLs -> not a crash; a manual/derived source.
    result = run_dumper_check(FakeDumper(release=None, urls=[]))
    assert result.status == "unsupported"


def test_run_dumper_check_not_implemented_is_unsupported():
    result = run_dumper_check(FakeDumper(raise_exc=NotImplementedError("Define in subclass")))
    assert result.status == "unsupported"


def test_check_plugin_unsupported(fixture_repo):
    ref = PluginRef(
        repo="testrepo",
        name="uploadonly",
        plugin_type="manifest",
        path=fixture_repo / "plugins" / "uploadonly",
        manifest_path=fixture_repo / "plugins" / "uploadonly" / "manifest.json",
    )
    result = check_plugin(ref, get_settings())
    assert result.status == "unsupported"
