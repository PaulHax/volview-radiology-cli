"""Geometry tests for the pure ITK ``assemble`` core.

``itk`` is NOT importable in the offline gate harness, so these SKIP there and
RUN in the Docker image (which has itk) or by the human driver -- see the chunk
notes. They are the regression wall for the single-slice ``[1, 1, 1]`` spacing
bug: a multi-slice DICOM series must come back with correct, metadata-derived
z-spacing regardless of the order the files are handed in.
"""
import os
import random

import numpy as np
import pytest

itk = pytest.importorskip("itk")

from conftest import DICOM_SERIES_DIR, DICOM_TWO_SERIES_DIR  # noqa: E402
from volview_cli_base.assemble import (  # noqa: E402
    assemble,
    to_scalar_float,
    write_image,
)

# The synthetic fixture geometry (see tests/fixtures gen script).
EXPECTED_SIZE = [16, 16, 8]
EXPECTED_SPACING = [0.7, 0.7, 2.5]
_SERIES_FILES = sorted(
    os.path.join(DICOM_SERIES_DIR, f)
    for f in os.listdir(DICOM_SERIES_DIR)
    if f.endswith(".dcm")
)


def _size(image):
    s = image.GetLargestPossibleRegion().GetSize()
    return [s[i] for i in range(image.GetImageDimension())]


def _spacing(image):
    sp = image.GetSpacing()
    return [sp[i] for i in range(image.GetImageDimension())]


# --- the multi-slice DICOM regression ------------------------------------

def test_multislice_series_recovers_metadata_spacing():
    """z-spacing must be 2.5 (from ImagePositionPatient), never a defaulted 1."""
    image = assemble(_SERIES_FILES)
    assert _size(image) == EXPECTED_SIZE
    sx, sy, sz = _spacing(image)
    assert sx == pytest.approx(0.7, abs=1e-3)
    assert sy == pytest.approx(0.7, abs=1e-3)
    # The bug this whole chunk exists to kill: a single-slice-style read would
    # leave sz == 1.0. Assert it is the true inter-slice distance.
    assert sz == pytest.approx(2.5, abs=1e-3)
    assert abs(sz - 1.0) > 0.5


def test_multislice_series_is_sorted_by_metadata_not_input_order():
    """The fixtures' filenames are in REVERSE z order; assemble must ignore
    that and produce a monotonic intensity ramp along z (0,100,..,700)."""
    image = assemble(_SERIES_FILES)
    arr = itk.array_from_image(image)  # shape (z, y, x)
    # (y=8, x=8) is outside the bright corner block, so it is the pure ramp.
    ramp = [float(arr[k, 8, 8]) for k in range(arr.shape[0])]
    assert sorted(set(round(v) for v in ramp)) == [0, 100, 200, 300, 400,
                                                    500, 600, 700]
    # metadata order => strictly monotonic (ascending or descending), never the
    # scrambled sequence a filename-order read would give.
    assert ramp == sorted(ramp) or ramp == sorted(ramp, reverse=True)


def test_assemble_ignores_input_path_order():
    """Shuffling the input paths yields identical geometry + pixels (assemble
    re-sorts by DICOM metadata, so caller order is advisory only)."""
    ordered = assemble(_SERIES_FILES)
    shuffled_paths = list(_SERIES_FILES)
    random.Random(1234).shuffle(shuffled_paths)
    shuffled = assemble(shuffled_paths)
    assert _spacing(ordered) == pytest.approx(_spacing(shuffled))
    np.testing.assert_array_equal(
        itk.array_from_image(ordered), itk.array_from_image(shuffled)
    )


# --- single-file path -----------------------------------------------------

def test_single_file_roundtrips_geometry(tmp_path):
    arr = np.arange(5 * 6 * 7, dtype=np.float32).reshape((7, 6, 5))  # (z,y,x)
    image = itk.image_from_array(arr)
    image.SetSpacing([1.1, 2.2, 3.3])  # (x, y, z)
    path = str(tmp_path / "vol.nrrd")
    write_image(image, path)

    back = assemble([path])
    assert _size(back) == [5, 6, 7]
    assert _spacing(back) == pytest.approx([1.1, 2.2, 3.3], abs=1e-4)
    np.testing.assert_allclose(itk.array_from_image(back), arr)


def test_write_image_creates_parent_dirs(tmp_path):
    arr = np.zeros((2, 3, 4), dtype=np.float32)
    image = itk.image_from_array(arr)
    nested = str(tmp_path / "a" / "b" / "out.nii.gz")
    write_image(image, nested)
    assert os.path.exists(nested)


# --- scalar/float conversion ---------------------------------------------

def test_to_scalar_float_preserves_geometry():
    image = assemble(_SERIES_FILES)
    scalar = to_scalar_float(image)
    assert itk.array_from_image(scalar).dtype == np.float32
    assert _spacing(scalar) == pytest.approx(EXPECTED_SPACING, abs=1e-3)
    assert _size(scalar) == EXPECTED_SIZE


# --- fail closed ----------------------------------------------------------

def test_assemble_empty_raises():
    with pytest.raises(ValueError):
        assemble([])


def test_assemble_multiple_non_dicom_fails_closed(tmp_path):
    a = str(tmp_path / "a.nrrd")
    b = str(tmp_path / "b.nrrd")
    for p in (a, b):
        write_image(itk.image_from_array(np.zeros((2, 2, 2), np.float32)), p)
    with pytest.raises(ValueError):
        assemble([a, b])


def test_assemble_multiple_dicom_series_fails_closed():
    """Two distinct SeriesInstanceUIDs in one input must RAISE, not silently
    keep the first series and drop the rest (the ``series_uids[0]`` fail-closed
    fix). The committed fixture holds two series so the guard is exercised by
    itk's own GDCM series detection, no pydicom needed at test time."""
    paths = [
        os.path.join(DICOM_TWO_SERIES_DIR, f)
        for f in os.listdir(DICOM_TWO_SERIES_DIR)
        if f.endswith(".dcm")
    ]
    assert len(paths) > 1
    with pytest.raises(ValueError, match="series"):
        assemble(paths)
