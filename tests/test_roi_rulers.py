import csv

import numpy as np
import pytest

from volview_cli_base.roi_rulers import (
    CSV_COLUMNS,
    axial_image_axis,
    index_existing_rulers,
    labelmap_segments,
    measure_label,
    measure_slice,
    measurement_label,
    orphan_rows,
    parse_measurement_label,
    ruler_length_mm,
    segment_rows,
    write_csv,
)


def ruler(label, first, second):
    return {
        "firstPoint": first,
        "secondPoint": second,
        "frameOfReference": {"planeNormal": [0, 0, 1], "planeOrigin": [0, 0, 0]},
        "labelName": label,
    }


def rows_by_region(rows):
    return {row["region_of_interest"]: row for row in rows}


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label, expected",
    [
        ("n2 LD", ("n2", "LD")),
        ("n2 SAD", ("n2", "SAD")),
        ("n2-ld", ("n2", "LD")),
        ("N01_sad", ("N01", "SAD")),
        ("P01: LD", ("P01", "LD")),
        ("  n2 LD  ", ("n2", "LD")),
    ],
)
def test_measurement_labels_parse_across_separators_and_case(label, expected):
    assert parse_measurement_label(label) == expected


@pytest.mark.parametrize("label", ["", "LD", "SAD", "WELD", "n2", "lymph node", None])
def test_non_measurement_labels_do_not_parse(label):
    assert parse_measurement_label(label) is None


def test_generated_label_round_trips_through_the_parser():
    label = measurement_label("n2", "LD")
    assert label == "n2 LD"
    assert parse_measurement_label(label) == ("n2", "LD")


def test_rulers_group_by_measurement_and_keep_the_unparsed():
    annotations = {
        "tools": {
            "rulers": [
                ruler("n2 LD", [0, 0, 0], [3, 4, 0]),
                ruler("n2 SAD", [0, 0, 0], [0, 1, 0]),
                {**ruler("", [0, 0, 0], [1, 0, 0]), "name": "scratch"},
            ]
        }
    }

    existing, unparsed = index_existing_rulers(annotations)

    assert set(existing) == {("n2", "LD"), ("n2", "SAD")}
    assert unparsed == ["scratch"]


def test_per_tool_name_is_the_fallback_when_no_label_is_assigned():
    annotations = {
        "tools": {"rulers": [{**ruler("", [0, 0, 0], [1, 0, 0]), "name": "n7-LD"}]}
    }
    existing, unparsed = index_existing_rulers(annotations)
    assert list(existing) == [("n7", "LD")]
    assert unparsed == []


def test_missing_tools_are_tolerated():
    assert index_existing_rulers({}) == ({}, [])
    assert index_existing_rulers(None) == ({}, [])


def test_ruler_length_is_the_world_distance():
    assert ruler_length_mm(ruler("n2 LD", [0, 0, 0], [3, 4, 0])) == 5.0
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
    assert labelmap_segments(metadata, [2, 5]) == [("n2", 2), ("Region 5", 5)]


def test_existing_rulers_are_reported_and_never_regenerated():
    segments = [("n2", 1)]
    measurements = {1: {"slice": 4, "ld_mm": 99.0, "sad_mm": 88.0}}
    existing = {("n2", "LD"): [ruler("n2 LD", [0, 0, 0], [3, 4, 0])]}

    rows = segment_rows(segments, measurements, existing, {1: 10}, 2.0)

    row = rows[0]
    assert row["ld_length_mm"] == "5"  # the placed ruler, not the derived 99
    assert row["ld_source"] == "existing"
    assert row["sad_length_mm"] == "88"
    assert row["sad_source"] == "generated"
    assert row["volume_mm3"] == "20"
    assert row["volume_ml"] == "0.02"
    assert row["voxel_count"] == "10"
    assert row["warnings"] == ""


def test_a_region_with_no_voxels_is_reported_rather_than_dropped():
    rows = segment_rows([("n2", 1)], {}, {}, {}, 1.0)

    row = rows[0]
    assert row["voxel_count"] == "0"
    assert row["ld_source"] == ""
    assert "zero_volume" in row["warnings"]
    assert "no_ld" in row["warnings"]
    assert "no_sad" in row["warnings"]


def test_duplicate_measurements_are_counted_as_a_warning():
    existing = {
        ("n2", "LD"): [
            ruler("n2 LD", [0, 0, 0], [3, 4, 0]),
            ruler("n2 LD", [0, 0, 0], [6, 8, 0]),
        ]
    }
    rows = segment_rows(
        [("n2", 1)], {1: {"slice": 0, "ld_mm": 1.0, "sad_mm": 1.0}}, existing, {1: 1}, 1.0
    )

    assert rows[0]["ld_length_mm"] == "5;10"
    assert "ld_count=2" in rows[0]["warnings"]


def test_two_segments_sharing_a_name_are_flagged():
    segments = [("n2", 1), ("n2", 2)]
    rows = segment_rows(segments, {}, {}, {1: 1, 2: 1}, 1.0)

    assert all("duplicate_segment_name" in row["warnings"] for row in rows)


def test_a_ruler_naming_no_segment_becomes_its_own_row():
    existing = {("n9", "LD"): [ruler("n9 LD", [0, 0, 0], [3, 4, 0])]}

    rows = orphan_rows(existing, ["scratch"], named_segments={"n2"})

    orphan = rows_by_region(rows)["n9"]
    assert orphan["ld_length_mm"] == "5"
    assert orphan["label_value"] == ""
    assert orphan["warnings"] == "no_matching_segment"

    unparsed = rows_by_region(rows)["scratch"]
    assert unparsed["warnings"] == "unparsed_ruler_label"


def test_a_ruler_matching_a_painted_segment_is_not_an_orphan():
    existing = {("n2", "LD"): [ruler("n2 LD", [0, 0, 0], [1, 0, 0])]}
    assert orphan_rows(existing, [], named_segments={"n2"}) == []


def test_csv_carries_the_declared_columns_and_a_header_when_empty(tmp_path):
    output = tmp_path / "nested" / "report.csv"
    write_csv([], output)

    with output.open(newline="", encoding="utf-8") as stream:
        assert list(csv.reader(stream)) == [list(CSV_COLUMNS)]


def test_csv_round_trips_a_report(tmp_path):
    output = tmp_path / "report.csv"
    rows = segment_rows(
        [("n2", 1)], {1: {"slice": 3, "ld_mm": 12.5, "sad_mm": 6.25}}, {}, {1: 4}, 1.0
    )
    write_csv(rows, output)

    with output.open(newline="", encoding="utf-8") as stream:
        written = list(csv.DictReader(stream))

    assert written[0]["region_of_interest"] == "n2"
    assert written[0]["ld_length_mm"] == "12.5"
    assert written[0]["sad_source"] == "generated"
    assert written[0]["slice"] == "3"
