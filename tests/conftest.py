"""Shared test setup.

Ensures the BioThings SDK config points at a throwaway temp dir *before* any
hub import happens during collection.
"""

import os
import pathlib
import tempfile

os.environ.setdefault(
    "PULSE_HUB_ROOT", tempfile.mkdtemp(prefix="pulse_test_hub_")
)

import pytest  # noqa: E402

FIXTURE_REPO = pathlib.Path(__file__).parent / "fixtures" / "repo"


@pytest.fixture
def fixture_repo() -> pathlib.Path:
    return FIXTURE_REPO
