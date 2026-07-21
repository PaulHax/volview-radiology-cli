"""Masked-composite primitives (``volview_cli_base.masked``).

The filtered volume is kept only inside the nonzero labelmap. The original
background and the labelmap's native integer dtype are otherwise preserved.
"""
import numpy as np
import pytest

from volview_cli_base.masked import composite_inside_mask, nonzero_mask


def test_nonzero_mask_selects_any_nonzero_label():
    # Distinct integer labels (0 background, 1/2/5 foreground) -- an integer
    # array, never float-cast: every nonzero label is selected.
    labelmap = np.array([[0, 1, 2], [5, 0, 0]], dtype=np.uint8)
    mask = nonzero_mask(labelmap)
    assert mask.dtype == np.bool_
    np.testing.assert_array_equal(
        mask, np.array([[False, True, True], [True, False, False]])
    )


def test_nonzero_mask_preserves_integer_labels_no_cast():
    # The mask is derived without mutating or casting the labelmap; the input
    # keeps its exact integer values.
    labelmap = np.array([0, 3, 0, 7], dtype=np.int16)
    _ = nonzero_mask(labelmap)
    assert labelmap.dtype == np.int16
    np.testing.assert_array_equal(labelmap, np.array([0, 3, 0, 7], dtype=np.int16))


def test_composite_keeps_filtered_inside_and_background_outside():
    background = np.array([[10.0, 20.0, 30.0], [40.0, 50.0, 60.0]], dtype=np.float32)
    filtered = np.zeros_like(background)  # a distinguishable "filtered" value
    mask = np.array([[False, True, False], [True, True, False]])

    out = composite_inside_mask(background, filtered, mask)

    # Inside the mask -> filtered (0); outside -> the original background.
    expected = np.array([[10.0, 0.0, 30.0], [0.0, 0.0, 60.0]], dtype=np.float32)
    np.testing.assert_array_equal(out, expected)
    assert out.dtype == background.dtype


def test_composite_empty_mask_is_pure_background():
    background = np.arange(6, dtype=np.float32).reshape(2, 3)
    filtered = background + 100.0
    mask = np.zeros((2, 3), dtype=bool)
    out = composite_inside_mask(background, filtered, mask)
    np.testing.assert_array_equal(out, background)


def test_composite_shape_mismatch_fails_closed():
    background = np.zeros((2, 3), dtype=np.float32)
    filtered = np.zeros((2, 3), dtype=np.float32)
    mask = np.zeros((2, 4), dtype=bool)  # different voxel grid
    with pytest.raises(ValueError):
        composite_inside_mask(background, filtered, mask)
