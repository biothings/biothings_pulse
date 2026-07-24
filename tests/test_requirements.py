from biothings_pulse.config import RepoSpec
from biothings_pulse.plugins.requirements import collect_repo_requirements


def test_collect_repo_requirements_inline_and_files(tmp_path):
    repo = tmp_path / "some.hub"
    repo.mkdir()
    (repo / "reqs.txt").write_text(
        "pandas>=1.0   # a comment\n"
        "\n"
        "-r other.txt\n"
        "biothings==1.0  # must be skipped (Pulse controls the SDK)\n"
    )
    spec = RepoSpec(
        name="some.hub",
        git_url="x",
        requirements=["lxml", "biothings"],  # biothings dropped
        requirements_files=["reqs.txt"],
    )
    reqs = collect_repo_requirements([spec], {"some.hub": repo})
    assert "lxml" in reqs
    assert "pandas>=1.0" in reqs
    assert not any(r.lower().startswith("biothings") for r in reqs)
    assert not any(r.startswith("-") for r in reqs)


def test_collect_repo_requirements_empty(tmp_path):
    spec = RepoSpec(name="r", git_url="x")  # no requirements / files
    assert collect_repo_requirements([spec], {"r": tmp_path}) == []
