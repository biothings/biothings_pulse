"""Opt-in integration test that hits the network and clones a real repo.

Run with:  pytest -m integration
"""

import pytest

from biothings_pulse.checker.runner import check_plugin
from biothings_pulse.config import RepoSpec, get_settings
from biothings_pulse.plugins.discovery import discover_plugins
from biothings_pulse.plugins.sync import sync_repo

pytestmark = pytest.mark.integration


def test_check_real_pending_api_chebi(tmp_path):
    settings = get_settings()
    spec = RepoSpec(
        name="pending.api",
        git_url="https://github.com/biothings/pending.api.git",
        manifest_globs=["plugins/*/manifest.json"],
        advanced_globs=["**/hub/dataload/sources/*", "plugins/*"],
    )
    repo_path = sync_repo(spec, tmp_path, depth=1)
    refs = {r.name: r for r in discover_plugins("pending.api", repo_path, spec)}
    assert "chebi" in refs

    result = check_plugin(refs["chebi"], settings)
    assert result.status == "ok"
    assert result.latest_version  # some version string
    assert result.download_urls  # at least one URL, nothing downloaded
