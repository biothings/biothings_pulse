from biothings_pulse.plugins.requirements import collect_repo_requirements


def test_collect_repo_requirements_reads_requirements_hub(tmp_path):
    repo = tmp_path / "some.hub"
    repo.mkdir()
    (repo / "requirements_hub.txt").write_text(
        "lxml # bs4 parsing\n"
        "pandas>=1.0.1   # sider parser\n"
        "\n"
        "-r requirements_common.txt\n"
        "biothings==1.0  # must be skipped (Pulse controls the SDK)\n"
    )
    reqs = collect_repo_requirements([repo])
    assert "lxml" in reqs
    assert "pandas>=1.0.1" in reqs
    assert not any(r.lower().startswith("biothings") for r in reqs)
    assert not any(r.startswith("-") for r in reqs)


def test_collect_repo_requirements_missing_file(tmp_path):
    assert collect_repo_requirements([tmp_path]) == []
