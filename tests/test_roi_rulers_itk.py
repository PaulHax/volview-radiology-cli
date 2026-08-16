"""The voxel-index-to-world half of the ruler task, against real ITK geometry.

The planar measurement is covered without ITK in ``test_roi_rulers``. What
needs a real image is the bridge: that a measurement found in array indices
becomes a ruler in world LPS millimetres whose length matches, and whose plane
the annotations contract accepts.
"""

import csv
import json
import os
from types import SimpleNamespace

import numpy as np
import pytest

itk = pytest.importorskip("itk")

from conftest import DICOM_SERIES_DIR, DICOM_TWO_SERIES_DIR  # noqa: E402
from volview_cli_base.annotations import load_annotations  # noqa: E402
from volview_cli_base.roi_report import image_metadata, voxel_summary  # noqa: E402
from volview_cli_base.roi_rulers import (  # noqa: E402
    GENERATED_LABEL_STYLES,
    build_output_annotations,
    frame_of_reference,
    generated_ruler,
    labelmap_segments,
    measure_label,
    measurement_label,
    reject_multi_file_dicom_series,
    ruler_length_mm,
    slice_axis_and_spacing,
    world_point,
)
from volview_cli_base.segnrrd import write_segmentation  # noqa: E402
from RegionOfInterestRulers.RegionOfInterestRulers import main  # noqa: E402


def bar_labelmap(spacing=(1.0, 1.0, 1.0)):
    """A 6-voxel horizontal bar of label 1 on slice k=1."""
    labels = np.zeros((3, 8, 9), dtype=np.uint8)  # (k, j, i)
    labels[1, 4, 2:8] = 1
    image = itk.image_from_array(labels)
    image.SetSpacing(list(spacing))
    return image


def run_main(tmp_path, base_path, labelmap_paths, input_annotations=""):
    """Run ``RegionOfInterestRulers.main`` and parse its report and annotations."""
    annotations_path = tmp_path / "rulers.annotations.json"
    report_path = tmp_path / "report.csv"
    main(
        SimpleNamespace(
            inputVolume=str(base_path),
            inputLabelmap=",".join(str(path) for path in labelmap_paths),
            inputAnnotations=input_annotations,
            outputAnnotations=str(annotations_path),
            outputReport=str(report_path),
            girderApiUrl="",
            girderToken="",
        )
    )
    with report_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    annotations = json.loads(annotations_path.read_text(encoding="utf-8"))
    return rows, annotations


def test_slice_axis_follows_the_superior_image_axis():
    image = bar_labelmap(spacing=(0.5, 0.75, 4.0))

    slice_axis, in_plane_spacing, in_plane_axes = slice_axis_and_spacing(image)

    # Identity direction: image axis 2 is superior, so array axis 0 stacks.
    assert slice_axis == 0
    assert in_plane_axes == [1, 2]
    # Array axes 1 and 2 are image axes 1 and 0 -- their spacings, in that order.
    assert in_plane_spacing == [0.75, 0.5]


def test_world_point_matches_itk_and_honors_spacing_and_origin():
    image = bar_labelmap(spacing=(0.5, 2.0, 4.0))
    image.SetOrigin([10.0, 20.0, 30.0])

    # Array index (k, j, i) = (1, 4, 2) is image index (2, 4, 1).
    assert world_point(image, [1, 4, 2]) == pytest.approx(
        [10.0 + 2 * 0.5, 20.0 + 4 * 2.0, 30.0 + 1 * 4.0]
    )


def test_generated_ruler_length_matches_the_measured_millimetres():
    spacing = (0.5, 2.0, 4.0)
    image = bar_labelmap(spacing=spacing)
    slice_axis, in_plane_spacing, in_plane_axes = slice_axis_and_spacing(image)

    measurement = measure_label(
        itk.array_view_from_image(image), 1, slice_axis, in_plane_spacing
    )
    ruler = generated_ruler(
        image, slice_axis, in_plane_axes, measurement, "LD", "n2 LD"
    )

    # The bar spans 5 voxel steps along image axis 0, whose spacing is 0.5mm.
    assert measurement["ld_mm"] == pytest.approx(2.5)
    assert ruler_length_mm(ruler) == pytest.approx(measurement["ld_mm"])
    assert ruler["labelName"] == "n2 LD"
    assert ruler["slice"] == 1


def test_generated_frame_is_axis_aligned_and_sits_on_the_measured_slice():
    image = bar_labelmap(spacing=(1.0, 1.0, 4.0))
    slice_axis, _, _ = slice_axis_and_spacing(image)

    frame = frame_of_reference(image, slice_axis, 1)

    assert frame["planeNormal"] == pytest.approx([0.0, 0.0, 1.0])
    # Slice 1 along the superior axis, whose spacing is 4mm.
    assert frame["planeOrigin"] == pytest.approx([0.0, 0.0, 4.0])


def test_generated_rulers_pass_the_annotations_contract():
    image = bar_labelmap()
    slice_axis, in_plane_spacing, in_plane_axes = slice_axis_and_spacing(image)
    measurement = measure_label(
        itk.array_view_from_image(image), 1, slice_axis, in_plane_spacing
    )

    rulers = []
    styles = {}
    for kind in ("LD", "SAD"):
        label = measurement_label("n2", kind)
        ruler = generated_ruler(
            image, slice_axis, in_plane_axes, measurement, kind, label
        )
        if ruler is not None:
            rulers.append(ruler)
            styles[label] = GENERATED_LABEL_STYLES[kind]

    output = build_output_annotations(rulers, styles, {})

    # Fail-closed validation is the real assertion: a session-only field, an
    # oblique frame, or a label the namespace does not declare would raise.
    assert load_annotations(output) is output
    assert [tool["labelName"] for tool in output["tools"]["rulers"]] == ["n2 LD"]


def test_an_input_label_style_survives_a_re_run():
    theirs = {"color": "#123456", "strokeWidth": 9}
    output = build_output_annotations(
        [
            {
                "firstPoint": [0.0, 0.0, 0.0],
                "secondPoint": [1.0, 0.0, 0.0],
                "frameOfReference": {
                    "planeNormal": [0.0, 0.0, 1.0],
                    "planeOrigin": [0.0, 0.0, 0.0],
                },
                "labelName": "n2 LD",
            }
        ],
        {"n2 LD": GENERATED_LABEL_STYLES["LD"]},
        {"labels": {"rulers": {"n2 LD": theirs}}},
    )

    assert output["labels"]["rulers"]["n2 LD"] == theirs
    assert load_annotations(output) is output


def test_no_rulers_still_produces_a_valid_empty_result():
    output = build_output_annotations([], {}, {})
    assert load_annotations(output) is output
    assert output["tools"]["rulers"] == []


def test_segment_names_reach_the_ruler_labels_through_seg_nrrd(tmp_path):
    image = bar_labelmap()
    path = tmp_path / "regions.seg.nrrd"
    write_segmentation(
        image, path, [{"value": 1, "name": "n2", "color": [20, 40, 60, 255]}]
    )

    restored = itk.imread(path)
    counts, _ = voxel_summary(itk.array_view_from_image(restored), restored.GetSpacing())
    segments = labelmap_segments(image_metadata(restored), list(counts))

    assert segments == [("n2", 1)]
    assert measurement_label(segments[0][0], "LD") == "n2 LD"


def test_ruler_task_aggregates_every_input_labelmap(tmp_path):
    first = bar_labelmap()
    second = bar_labelmap()
    first_path = tmp_path / "first.seg.nrrd"
    second_path = tmp_path / "second.seg.nrrd"
    write_segmentation(
        first,
        first_path,
        [{"value": 1, "name": "first region", "color": [255, 0, 0, 255]}],
    )
    write_segmentation(
        second,
        second_path,
        [{"value": 1, "name": "second region", "color": [0, 255, 0, 255]}],
    )

    base_path = tmp_path / "base.nrrd"
    itk.imwrite(first, base_path)
    rows, annotations = run_main(tmp_path, base_path, [first_path, second_path])

    assert [row["roi_name"] for row in rows] == ["first region", "second region"]
    assert [ruler["labelName"] for ruler in annotations["tools"]["rulers"]] == [
        "first region LD",
        "second region LD",
    ]


def test_duplicate_segment_name_across_labelmaps_is_flagged_in_every_row(tmp_path):
    first = bar_labelmap()
    second = bar_labelmap()
    first_path = tmp_path / "first.seg.nrrd"
    second_path = tmp_path / "second.seg.nrrd"
    write_segmentation(
        first, first_path, [{"value": 1, "name": "n2", "color": [255, 0, 0, 255]}]
    )
    write_segmentation(
        second, second_path, [{"value": 1, "name": "n2", "color": [0, 255, 0, 255]}]
    )

    base_path = tmp_path / "base.nrrd"
    itk.imwrite(first, base_path)
    rows, _ = run_main(tmp_path, base_path, [first_path, second_path])

    assert [row["roi_name"] for row in rows] == ["n2", "n2"]
    assert [row["labelmap_index"] for row in rows] == ["1", "2"]
    for row in rows:
        assert (
            "Multiple segmentation labels are named 'n2'; ruler matching is "
            "ambiguous." in row["warnings"]
        )


# ---------------------------------------------------------------------------
# Multi-file DICOM series as a labelmap input
# ---------------------------------------------------------------------------


def test_a_single_dicom_labelmap_file_is_unaffected():
    reject_multi_file_dicom_series([os.path.join(DICOM_SERIES_DIR, "slice000.dcm")])


def test_two_files_from_the_same_dicom_series_are_rejected():
    paths = [
        os.path.join(DICOM_SERIES_DIR, "slice000.dcm"),
        os.path.join(DICOM_SERIES_DIR, "slice001.dcm"),
    ]
    with pytest.raises(ValueError, match="same DICOM series"):
        reject_multi_file_dicom_series(paths)


def test_dicom_files_from_different_series_are_not_rejected():
    paths = [
        os.path.join(DICOM_SERIES_DIR, "slice000.dcm"),
        os.path.join(DICOM_TWO_SERIES_DIR, "series0_slice000.dcm"),
    ]
    reject_multi_file_dicom_series(paths)


def test_non_dicom_labelmaps_are_never_flagged(tmp_path):
    first = bar_labelmap()
    second = bar_labelmap()
    first_path = tmp_path / "first.seg.nrrd"
    second_path = tmp_path / "second.seg.nrrd"
    write_segmentation(
        first, first_path, [{"value": 1, "name": "n2", "color": [255, 0, 0, 255]}]
    )
    write_segmentation(
        second, second_path, [{"value": 1, "name": "n2", "color": [0, 255, 0, 255]}]
    )
    reject_multi_file_dicom_series([str(first_path), str(second_path)])


def test_main_rejects_a_multi_file_dicom_series_as_the_labelmap_input(tmp_path):
    labelmap_paths = [
        os.path.join(DICOM_SERIES_DIR, "slice000.dcm"),
        os.path.join(DICOM_SERIES_DIR, "slice001.dcm"),
    ]
    base_path = tmp_path / "base.nrrd"
    itk.imwrite(bar_labelmap(), base_path)

    with pytest.raises(ValueError, match="same DICOM series"):
        run_main(tmp_path, base_path, labelmap_paths)
