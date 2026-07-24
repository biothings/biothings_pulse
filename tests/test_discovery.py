from pathlib import Path

from biothings_pulse.config import RepoSpec
from biothings_pulse.plugins.discovery import _source_url, discover_plugins


def _spec():
    return RepoSpec(
        name="testrepo",
        git_url="x",
        manifest_globs=["plugins/*/manifest.json"],
        advanced_globs=["**/hub/dataload/sources/*", "plugins/*"],
    )


def test_discovers_both_plugin_types(fixture_repo):
    refs = discover_plugins("testrepo", fixture_repo, _spec())
    by_name = {r.name: r for r in refs}

    # Manifest plugins (incl. the upload-only one, which the loader later flags
    # as unsupported rather than discovery hiding it).
    assert by_name["acme"].plugin_type == "manifest"
    assert by_name["acme"].manifest_path is not None
    assert by_name["basic"].plugin_type == "manifest"
    assert by_name["uploadonly"].plugin_type == "manifest"

    # Advanced plugin under hub/dataload/sources/.
    assert by_name["widget"].plugin_type == "advanced"


def test_source_url_github_and_other_hosts():
    gh = RepoSpec(name="r", git_url="https://github.com/biothings/pending.api.git")
    assert (
        _source_url(gh, Path("/r"), Path("/r/plugins/chebi"))
        == "https://github.com/biothings/pending.api/tree/HEAD/plugins/chebi"
    )
    # explicit ref
    ghr = RepoSpec(name="r", git_url="https://github.com/o/repo.git", ref="main")
    assert _source_url(ghr, Path("/r"), Path("/r/plugins/x")).endswith(
        "/tree/main/plugins/x"
    )
    # non-GitHub host -> link to the repo root (no /tree deep link)
    gl = RepoSpec(name="r", git_url="https://gitlab.com/o/repo.git")
    assert _source_url(gl, Path("/r"), Path("/r/plugins/x")) == "https://gitlab.com/o/repo"


def test_manifest_wins_over_advanced_on_name_clash(fixture_repo):
    # 'acme' has a manifest and also matches the plugins/* advanced glob; the
    # manifest classification must win and there must be no duplicate.
    refs = discover_plugins("testrepo", fixture_repo, _spec())
    acme = [r for r in refs if r.name == "acme"]
    assert len(acme) == 1
    assert acme[0].plugin_type == "manifest"
