"""End-to-end masked-median-filter pipeline over real ITK images.

``itk`` is NOT importable in the offline gate harness, so these SKIP there and
RUN in the Docker image (which has itk) or by the human driver -- the same
pattern as ``test_assemble``. They mirror ``MaskedMedianFilter.main`` (without
its ``slicer_cli_web`` shell) to lock two Chunk 16 pins:

- the labelmap is read by ``assemble`` with its integer label values intact (no
  float cast), so a nonzero-label mask is exact;
- the median filter is applied ONLY inside the mask -- an intensity spike inside
  is smoothed away, while a spike OUTSIDE keeps its original value (the composite
  is load-bearing, not a whole-image filter).
"""
import numpy as np
import pytest

itk = pytest.importorskip("itk")

from volview_cli_base.assemble import assemble, to_scalar_float, write_image  # noqa: E402
from volview_cli_base.masked import composite_inside_mask, nonzero_mask  # noqa: E402


def _spacing(image):
    sp = image.GetSpacing()
    return [sp[i] for i in range(image.GetImageDimension())]


def _run_masked_filter(background, labelmap, radius):
    """The pixel pipeline of ``MaskedMedianFilter.main``, minus the CLI shell."""
    image = to_scalar_float(background)
    filtered = itk.median_image_filter(image, radius=radius)
    mask = nonzero_mask(itk.array_view_from_image(labelmap))
    composed = composite_inside_mask(
        itk.array_view_from_image(image),
        itk.array_view_from_image(filtered),
        mask,
    )
    out = itk.image_from_array(composed)
    out.CopyInformation(image)
    return out


def test_assemble_preserves_integer_labelmap_values(tmp_path):
    """A uint8 labelmap round-trips through assemble as integers, values intact
    -- the CLI must read the mask without a float cast."""
    labels = np.zeros((4, 4, 4), dtype=np.uint8)
    labels[1:3, 1:3, 1:3] = 2  # a distinct nonzero label
    labels[0, 0, 0] = 1
    path = str(tmp_path / "seg.nrrd")
    write_image(itk.image_from_array(labels), path)

    read_back = itk.array_from_image(assemble([path]))
    assert np.issubdtype(read_back.dtype, np.integer)  # NOT float-cast
    np.testing.assert_array_equal(read_back, labels)


def test_masked_filter_smooths_inside_and_preserves_outside(tmp_path):
    # A constant field with one spike INSIDE the mask and one OUTSIDE it.
    background = np.full((6, 6, 6), 100.0, dtype=np.float32)
    background[3, 3, 3] = 1000.0  # inside the mask block below
    background[0, 0, 0] = 1000.0  # outside the mask (corner)

    labels = np.zeros((6, 6, 6), dtype=np.uint8)
    labels[2:4, 2:4, 2:4] = 1  # nonzero block containing (3,3,3), not (0,0,0)

    bg_image = itk.image_from_array(background)
    bg_image.SetSpacing([0.5, 0.5, 2.0])
    label_image = itk.image_from_array(labels)
    label_image.SetSpacing([0.5, 0.5, 2.0])

    out = _run_masked_filter(bg_image, label_image, radius=1)
    out_arr = itk.array_from_image(out)

    # Inside the mask: the spike is smoothed to the surrounding constant.
    assert out_arr[3, 3, 3] == pytest.approx(100.0)
    assert out_arr[3, 3, 3] != background[3, 3, 3]
    # Outside the mask: the original value is preserved (composite is load-bearing).
    assert out_arr[0, 0, 0] == pytest.approx(1000.0)
    # Everywhere outside the mask matches the original background exactly.
    outside = labels == 0
    np.testing.assert_array_equal(out_arr[outside], background[outside])
    # Geometry is preserved.
    assert _spacing(out) == pytest.approx([0.5, 0.5, 2.0], abs=1e-4)
