"""Make the repo root importable so ``import volview_cli_base`` works from the
tests exactly as it does when a CLI script inserts the root at runtime.
"""
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture(scope="session")
def dicom_fixtures(tmp_path_factory):
    from fixtures.generate_dicom import generate_dicom_fixtures

    directory = tmp_path_factory.mktemp("dicom")
    generate_dicom_fixtures(directory)
    return directory
