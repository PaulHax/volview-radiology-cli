"""Make the repo root importable so ``import volview_cli_base`` works from the
tests exactly as it does when a CLI script inserts the root at runtime.
"""
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
DICOM_SERIES_DIR = os.path.join(FIXTURES, "dicom_series")
DICOM_TWO_SERIES_DIR = os.path.join(FIXTURES, "dicom_two_series")
