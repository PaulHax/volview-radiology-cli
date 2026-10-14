import numpy as np
import pytest

from volview_cli_base.segment_rulers import (
    axial_image_axis,
    labelmap_segments,
    measure_label,
    measure_slice,
    ruler_length_mm,
)


def ruler(label, first, second):
    return {
        "firstPoint": first,
        "secondPoint": second,
        "frameOfReference": {"planeNormal": [0, 0, 1], "planeOrigin": [0, 0, 0]},
        "labelName": label,
    }


def test_ruler_length_is_the_world_distance():
    assert ruler_length_mm(ruler("n2", [0, 0, 0], [3, 4, 0])) == 5.0
    assert ruler_length_mm({"firstPoint": [0, 0, 0]}) is None


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_axial_axis_is_the_one_nearest_superior():
    identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    assert axial_image_axis(identity) == 2
    # A sagittally stored volume: image axis 0 carries the superior direction.
    sagittal = [[0, 1, 0], [0, 0, 1], [1, 0, 0]]
    assert axial_image_axis(sagittal) == 0


def test_slice_measurement_of_a_rectangle_uses_millimetre_spacing():
    mask = np.zeros((5, 9), dtype=bool)
    mask[1:4, 2:8] = True  # 3 rows by 6 columns

    measurement = measure_slice(mask, (2.0, 1.0))

    # Corner to corner: rows span (3-1)*2 = 4mm, columns span (7-2)*1 = 5mm.
    assert measurement["ld_mm"] == pytest.approx(np.hypot(4.0, 5.0))
    assert measurement["sad_mm"] > 0
    assert measurement["sad_mm"] <= measurement["ld_mm"]


def test_long_axis_of_a_horizontal_bar_is_its_length():
    mask = np.zeros((5, 9), dtype=bool)
    mask[2, 1:8] = True

    measurement = measure_slice(mask, (1.0, 1.0))

    assert measurement["ld_mm"] == pytest.approx(6.0)
    assert measurement["ld_points"] == ((2, 1), (2, 7))
    # A one-pixel-tall bar has no perpendicular extent to speak of.
    assert measurement["sad_mm"] == pytest.approx(0.0)


def test_a_mask_too_small_to_span_a_chord_has_no_measurement():
    single = np.zeros((3, 3), dtype=bool)
    single[1, 1] = True
    assert measure_slice(single, (1.0, 1.0)) is None
    assert measure_slice(np.zeros((3, 3), dtype=bool), (1.0, 1.0)) is None


def test_short_axis_of_an_ellipse_is_shorter_than_its_long_axis():
    rows, columns = np.ogrid[:41, :41]
    mask = ((rows - 20) / 6.0) ** 2 + ((columns - 20) / 18.0) ** 2 <= 1.0

    measurement = measure_slice(mask, (1.0, 1.0))

    assert measurement["ld_mm"] == pytest.approx(36.0, abs=1.0)
    assert measurement["sad_mm"] == pytest.approx(12.0, abs=1.5)


def test_label_measurement_picks_the_widest_slice():
    array = np.zeros((3, 7, 7), dtype=np.uint8)
    array[0, 3, 1:4] = 5  # 3 wide
    array[1, 3, 1:7] = 5  # 6 wide, the winner
    array[2, 3, 1:3] = 5  # 2 wide

    measurement = measure_label(array, 5, slice_axis=0, in_plane_spacing_mm=(1.0, 1.0))

    assert measurement["slice"] == 1
    assert measurement["ld_mm"] == pytest.approx(5.0)


def test_absent_label_has_no_measurement():
    array = np.zeros((2, 4, 4), dtype=np.uint8)
    assert measure_label(array, 9, 0, (1.0, 1.0)) is None


def test_hull_reduction_preserves_the_longest_chord():
    # A filled disc: the diameter must survive dropping interior points.
    rows, columns = np.ogrid[:31, :31]
    mask = (rows - 15) ** 2 + (columns - 15) ** 2 <= 14**2

    measurement = measure_slice(mask, (1.0, 1.0))

    points = np.argwhere(mask)
    deltas = points[:, None, :] - points[None, :, :]
    brute_force = float(np.sqrt((deltas**2).sum(axis=-1)).max())
    assert measurement["ld_mm"] == pytest.approx(brute_force)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def test_segments_are_named_from_metadata_with_a_fallback():
    metadata = {"Segment0_LabelValue": "2", "Segment0_Name": "n2"}
    assert labelmap_segments(metadata, [2, 5]) == [("n2", 2), ("Segment 5", 5)]
