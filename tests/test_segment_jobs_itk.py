"""Exercise the exposed ruler and measurement jobs with saved files."""

import csv
import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
import pytest

itk = pytest.importorskip("itk")
pytest.importorskip("slicer_cli_web")

from volview_cli_base.annotations import read_annotations  # noqa: E402
from volview_cli_base.segnrrd import write_segmentation  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
INTENSITY_COLUMNS = (
    "intensity_min", "intensity_max", "intensity_mean",
    "intensity_median", "intensity_stddev", "intensity_sum",
)
CSV_COLUMNS = (
    "input_image_path", "segment_name", "labelmap_index", "volume_mm3", "warnings",
    *INTENSITY_COLUMNS,
)


def run_cli(task, *arguments):
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "cli_list.py"), task, *map(str, arguments)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def save_labelmap(tmp_path, names, filename="regions.seg.nrrd", painted_values=None):
    labels = np.zeros((3, 7, len(names) * 8 + 2), dtype=np.uint8)
    for value in range(1, len(names) + 1):
        if painted_values is not None and value not in painted_values:
            continue
        labels[1, 2:5, value * 8 - 6:value * 8 - 2] = value
    image = itk.image_from_array(labels)
    image.SetSpacing([0.5, 2.0, 3.0])
    base_path = tmp_path / "original-volume.nrrd"
    if not base_path.exists():
        itk.imwrite(image, str(base_path))
    labelmap_path = tmp_path / filename
    write_segmentation(
        image,
        labelmap_path,
        [
            {"value": index, "name": name, "color": [255, 0, 0, 255]}
            for index, name in enumerate(names, start=1)
        ],
    )
    return labelmap_path


def saved_ruler(label, length, axis=0, name="Ruler"):
    endpoint = [0.0, 0.0, 0.0]
    endpoint[axis] = float(length)
    result = {
        "firstPoint": [0.0, 0.0, 0.0],
        "secondPoint": endpoint,
        "frameOfReference": {
            "planeNormal": [0.0, 0.0, 1.0],
            "planeOrigin": [0.0, 0.0, 0.0],
        },
        "name": name,
    }
    if label is not None:
        result["labelName"] = label
    return result


def save_annotations(tmp_path, rulers, filename="input.annotations.json"):
    annotations = {
        "schemaVersion": 1,
        "space": "LPS",
        "labels": {
            "rulers": {
                ruler["labelName"]: {"color": "#123456", "strokeWidth": 3}
                for ruler in rulers
                if ruler.get("labelName")
            }
        },
        "tools": {"rulers": rulers},
    }
    path = tmp_path / filename
    path.write_text(json.dumps(annotations), encoding="utf-8")
    return path


def run_report(tmp_path, labelmaps, annotations=None, filename="report.csv", volume=None):
    output = tmp_path / filename
    arguments = [
        volume or tmp_path / "original-volume.nrrd",
        ",".join(map(str, labelmaps)),
        output,
    ]
    if annotations is not None:
        arguments.extend(["--inputAnnotations", annotations])
    run_cli("ExportSegmentStatistics", *arguments)
    with output.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        assert fields[:len(CSV_COLUMNS)] == list(CSV_COLUMNS)
        assert fields[len(CSV_COLUMNS):] == [
            f"ruler_{index}_length_mm"
            for index in range(1, len(fields) - len(CSV_COLUMNS) + 1)
        ]
        return list(reader)


def ruler_values(row):
    return [value for column, value in row.items() if column.startswith("ruler_")]


def test_report_exports_every_saved_ruler_in_descending_order(tmp_path):
    names = [
        "T01", "T02", "Zone LD", "missing", "single", "crowded", "partial",
        "zero", "By name", "standalone LD", "duplicate", "duplicate",
    ]
    labelmap = save_labelmap(tmp_path, names)
    rulers = [
        saved_ruler("T01", 3, axis=1, name="incorrect LD"),
        saved_ruler("T01", 5, name="incorrect SAD"),
        saved_ruler("T02", 3),
        saved_ruler("T02", 7, axis=1),
        saved_ruler("Zone LD", 4, axis=1),
        saved_ruler("Zone LD", 6),
        saved_ruler("single", 9),
        saved_ruler("crowded", 2),
        saved_ruler("crowded", 5),
        saved_ruler("crowded", 4),
        saved_ruler("partial", 11),
        saved_ruler("zero", 0),
        saved_ruler("zero", 2),
        saved_ruler(None, 4, name="By name"),
        saved_ruler("", 6, axis=1, name="By name"),
        saved_ruler("standalone LD", 4),
        saved_ruler("duplicate", 8),
        saved_ruler("duplicate", 2, axis=1),
        saved_ruler("outside", 5),
        saved_ruler("outside", 2, axis=1),
    ]
    annotations = save_annotations(tmp_path, rulers)
    before = annotations.read_bytes()
    before_files = set(tmp_path.iterdir())

    rows = run_report(tmp_path, [labelmap], annotations)

    assert annotations.read_bytes() == before
    assert set(tmp_path.iterdir()) - before_files == {tmp_path / "report.csv"}
    assert len(rows) == len(names) + 1
    by_name = {row["segment_name"]: row for row in rows}
    expected = {
        "T01": ["5", "3", ""], "T02": ["7", "3", ""],
        "Zone LD": ["6", "4", ""], "By name": ["6", "4", ""],
        "single": ["9", "", ""], "crowded": ["5", "4", "2"],
        "partial": ["11", "", ""], "standalone LD": ["4", "", ""],
    }
    for name, lengths in expected.items():
        assert ruler_values(by_name[name]) == lengths
        assert by_name[name]["warnings"] == ""
    assert "Zone" not in by_name
    assert "incorrect" not in " ".join(by_name)
    assert ruler_values(by_name["missing"]) == ["", "", ""]
    assert "No rulers" in by_name["missing"]["warnings"]
    assert ruler_values(by_name["zero"]) == ["2", "0", ""]
    assert "positive finite length" in by_name["zero"]["warnings"]
    duplicate_rows = [row for row in rows if row["segment_name"] == "duplicate"]
    assert len(duplicate_rows) == 2
    for row in duplicate_rows:
        assert ruler_values(row) == ["8", "2", ""]
        assert "ambiguous" in row["warnings"]
    for row in rows[:-1]:
        assert row["volume_mm3"] == "36"
        assert row["labelmap_index"] == "1"
        assert row["input_image_path"] == ""
    orphan = by_name["outside"]
    assert ruler_values(orphan) == ["5", "2", ""]
    assert orphan["volume_mm3"] == orphan["labelmap_index"] == ""
    assert "No segmentation label matches" in orphan["warnings"]


@pytest.mark.parametrize("count", [0, 1, 3])
def test_report_creates_only_the_numbered_columns_needed(tmp_path, count):
    labelmap = save_labelmap(tmp_path, ["target"])
    annotations = save_annotations(
        tmp_path, [saved_ruler("target", length) for length in range(1, count + 1)]
    )

    row, = run_report(tmp_path, [labelmap], annotations)

    assert list(row) == [
        *CSV_COLUMNS, *[f"ruler_{index}_length_mm" for index in range(1, count + 1)],
    ]
    assert ruler_values(row) == [str(length) for length in range(count, 0, -1)]
    assert bool(row["warnings"]) == (count == 0)


def test_report_shares_columns_across_maps_and_unmatched_rulers(tmp_path):
    first = save_labelmap(tmp_path, ["first", "no rulers"], filename="first.seg.nrrd")
    second = save_labelmap(
        tmp_path, ["second", "empty"], filename="second.seg.nrrd", painted_values=[1]
    )
    annotations = save_annotations(tmp_path, [
        saved_ruler("first", 7), saved_ruler("second", 3), saved_ruler("second", 4),
        *[saved_ruler("outside", length) for length in [2, 10, 1, 9, 3, 8, 4, 7, 5, 6, 11]],
    ])

    rows = run_report(tmp_path, [first, second], annotations)

    assert [row["segment_name"] for row in rows] == ["first", "no rulers", "second", "outside"]
    assert list(rows[0]) == [
        *CSV_COLUMNS, *[f"ruler_{index}_length_mm" for index in range(1, 12)],
    ]
    assert ruler_values(rows[0]) == ["7", *[""] * 10]
    assert ruler_values(rows[1]) == [""] * 11
    assert ruler_values(rows[2]) == ["4", "3", *[""] * 9]
    assert ruler_values(rows[3]) == [str(length) for length in range(11, 0, -1)]
    assert rows[3]["labelmap_index"] == rows[3]["volume_mm3"] == ""


def test_report_retains_a_blank_slot_for_an_unrepresentable_length(tmp_path):
    labelmap = save_labelmap(tmp_path, ["target"])
    invalid = saved_ruler("target", 1e308)
    invalid["firstPoint"] = [-1e308, 0, 0]
    annotations = save_annotations(tmp_path, [
        invalid, saved_ruler("target", 0), saved_ruler("target", 4),
    ])
    original = annotations.read_bytes()

    row, = run_report(tmp_path, [labelmap], annotations)

    assert ruler_values(row) == ["4", "0", ""]
    assert "positive finite length" in row["warnings"]
    assert annotations.read_bytes() == original


def test_report_without_annotations_does_not_derive_rulers(tmp_path):
    labelmap = save_labelmap(tmp_path, ["painted region"])

    row, = run_report(tmp_path, [labelmap])

    assert row["volume_mm3"] == "36"
    assert list(row) == list(CSV_COLUMNS)
    assert "No rulers" in row["warnings"]
    assert not list(tmp_path.glob("*.annotations.json"))


def test_empty_labelmap_still_exports_the_csv_header(tmp_path):
    labelmap = save_labelmap(tmp_path, [])

    assert run_report(tmp_path, [labelmap]) == []
    with (tmp_path / "report.csv").open(newline="") as stream:
        assert next(csv.reader(stream)) == list(CSV_COLUMNS)


def test_report_detects_segment_name_collision_across_labelmaps(tmp_path):
    first = save_labelmap(tmp_path, ["shared"], filename="first.seg.nrrd")
    second = save_labelmap(tmp_path, ["shared"], filename="second.seg.nrrd")
    annotations = save_annotations(
        tmp_path, [saved_ruler("shared", 6), saved_ruler("shared", 2, axis=1)]
    )

    rows = run_report(tmp_path, [first, second], annotations)

    assert [row["labelmap_index"] for row in rows] == ["1", "2"]
    assert [row["volume_mm3"] for row in rows] == ["36", "36"]
    for row in rows:
        assert row["segment_name"] == "shared"
        assert ruler_values(row) == ["6", "2"]
        assert "ambiguous" in row["warnings"]


def test_generator_respects_saved_rulers_and_rerun_is_additive(tmp_path):
    labelmap = save_labelmap(tmp_path, ["manual", "zero", "unmeasured"])
    manual_rulers = [saved_ruler("manual", 8), saved_ruler("zero", 0)]
    input_path = save_annotations(tmp_path, manual_rulers)
    custom_style = {"color": "#abcdef", "strokeWidth": 5}
    saved = json.loads(input_path.read_text())
    saved["labels"]["rulers"]["unmeasured"] = custom_style
    input_path.write_text(json.dumps(saved), encoding="utf-8")
    before = input_path.read_bytes()
    generated_path = tmp_path / "generated.annotations.json"
    before_files = set(tmp_path.iterdir())

    run_cli(
        "GenerateSegmentRulers", tmp_path / "original-volume.nrrd", labelmap,
        generated_path, "--inputAnnotations", input_path,
    )

    assert input_path.read_bytes() == before
    assert set(tmp_path.iterdir()) - before_files == {generated_path}
    generated = read_annotations(generated_path)
    generated_rulers = generated["tools"]["rulers"]
    assert [ruler["labelName"] for ruler in generated_rulers] == ["unmeasured", "unmeasured"]
    assert [ruler["name"] for ruler in generated_rulers] == ["unmeasured", "unmeasured"]
    assert list(generated["labels"]["rulers"]) == ["unmeasured"]
    assert generated["labels"]["rulers"]["unmeasured"] == custom_style
    assert all(ruler["firstPoint"] != ruler["secondPoint"] for ruler in generated_rulers)
    merged_path = save_annotations(
        tmp_path, manual_rulers + generated_rulers, filename="merged.annotations.json"
    )
    second_path = tmp_path / "second.annotations.json"

    run_cli(
        "GenerateSegmentRulers", tmp_path / "original-volume.nrrd", labelmap,
        second_path, "--inputAnnotations", merged_path,
    )

    assert read_annotations(second_path)["tools"]["rulers"] == []
    rows = run_report(tmp_path, [labelmap], merged_path)
    by_name = {row["segment_name"]: row for row in rows}
    assert ruler_values(by_name["manual"]) == ["8", ""]
    assert ruler_values(by_name["zero"]) == ["0", ""]
    assert "positive finite length" in by_name["zero"]["warnings"]
    assert by_name["manual"]["warnings"] == by_name["unmeasured"]["warnings"] == ""


def test_both_jobs_are_discoverable_with_distinct_outputs():
    tasks = json.loads(run_cli("--list_cli"))
    assert "GenerateSegmentRulers" in tasks
    assert "ExportSegmentStatistics" in tasks
    assert {"RegionOfInterestRulers", "RegionOfInterestReport"}.isdisjoint(tasks)
    for task, title, output_name, extension in [
        ("GenerateSegmentRulers", "Generate Segment Rulers", "outputAnnotations",
         ".annotations.json"),
        ("ExportSegmentStatistics", "Export Segment Statistics", "outputReport", ".csv"),
    ]:
        spec = ElementTree.fromstring(run_cli(task, "--xml"))
        assert spec.findtext("title") == title
        parameters = [parameter for group in spec.findall("parameters")
                      for parameter in group if parameter.find("name") is not None]
        outputs = [parameter for parameter in parameters
                   if parameter.findtext("channel") == "output"]
        assert len(outputs) == 1
        assert outputs[0].findtext("name") == output_name
        assert outputs[0].findtext("index") == "2"
        assert outputs[0].attrib["fileExtensions"] == extension
        positions = {parameter.findtext("name"): parameter.findtext("index")
                     for parameter in parameters}
        assert positions["inputVolume"] == "0"
        assert positions["inputLabelmap"] == "1"
        existing = next(parameter for parameter in parameters
                        if parameter.findtext("name") == "inputAnnotations")
        assert existing.findtext("longflag") == "inputAnnotations"
        assert existing.find("default") is not None
        assert existing.findtext("index") is None


@pytest.mark.parametrize("suffix", ["LD", "SAD"])
@pytest.mark.parametrize("across_maps", [False, True])
def test_generator_labels_diameters_with_exact_segment_names(tmp_path, suffix, across_maps):
    suffix_name = "Tumor " + suffix
    if across_maps:
        labelmaps = [
            save_labelmap(tmp_path, ["Tumor", "unused"], filename="first.seg.nrrd",
                          painted_values=[1]),
            save_labelmap(tmp_path, ["unused", suffix_name], filename="second.seg.nrrd",
                          painted_values=[2]),
        ]
    else:
        labelmaps = [save_labelmap(tmp_path, ["Tumor", suffix_name])]
    inputs = {path: path.read_bytes() for path in labelmaps}
    output = tmp_path / "generated.annotations.json"

    run_cli("GenerateSegmentRulers", tmp_path / "original-volume.nrrd",
            ",".join(map(str, labelmaps)), output)

    generated = read_annotations(output)
    rulers = generated["tools"]["rulers"]
    assert generated["labels"]["rulers"] == {"Tumor": {}, suffix_name: {}}
    assert [ruler["labelName"] for ruler in rulers] == ["Tumor", "Tumor", suffix_name, suffix_name]
    assert [ruler["name"] for ruler in rulers] == ["Tumor", "Tumor", suffix_name, suffix_name]
    assert all(path.read_bytes() == before for path, before in inputs.items())
    rows = run_report(tmp_path, labelmaps, output)
    assert [row["segment_name"] for row in rows] == ["Tumor", suffix_name]
    assert all(len(ruler_values(row)) == 2 for row in rows)
    assert all(float(value) > 0 for row in rows for value in ruler_values(row))
    assert all(row["warnings"] == "" for row in rows)


@pytest.mark.parametrize("suffix", ["LD", "SAD"])
@pytest.mark.parametrize("declared,painted_values", [
    (True, []), (True, [1]), (True, [1, 2]), (False, [1]),
])
def test_report_keeps_distinct_literal_segment_names(
    tmp_path, suffix, declared, painted_values
):
    suffix_name = "Zone " + suffix
    names = ["Zone", suffix_name] if declared else ["Zone"]
    labelmap = save_labelmap(tmp_path, names, painted_values=painted_values)
    annotations = save_annotations(tmp_path, [
        saved_ruler("Zone", 8), saved_ruler("Zone", 3, axis=1),
        saved_ruler(suffix_name, 6), saved_ruler(suffix_name, 2, axis=1),
    ])

    rows = run_report(tmp_path, [labelmap], annotations)

    assert len(rows) == 2
    by_name = {row["segment_name"]: row for row in rows}
    for value, name, lengths in [(1, "Zone", ["8", "3"]), (2, suffix_name, ["6", "2"])]:
        row = by_name[name]
        assert ruler_values(row) == lengths
        assert "ambiguous" not in row["warnings"]
        if value in painted_values:
            assert row["volume_mm3"] == "36"
            assert row["labelmap_index"] == "1"
            assert row["warnings"] == ""
        else:
            assert row["volume_mm3"] == row["labelmap_index"] == ""
            assert "No segmentation label matches" in row["warnings"]


@pytest.mark.parametrize("suffix", ["LD", "SAD"])
@pytest.mark.parametrize("declared", [False, True])
def test_unpainted_group_does_not_suppress_another_segments_generation(
    tmp_path, suffix, declared
):
    suffix_name = "Zone " + suffix
    names = ["Zone", suffix_name] if declared else ["Zone"]
    labelmap = save_labelmap(tmp_path, names, painted_values=[1])
    annotations = save_annotations(tmp_path, [saved_ruler(suffix_name, 6)])
    output = tmp_path / "generated.annotations.json"
    original = annotations.read_bytes()

    run_cli("GenerateSegmentRulers", tmp_path / "original-volume.nrrd", labelmap,
            output, "--inputAnnotations", annotations)

    rulers = read_annotations(output)["tools"]["rulers"]
    assert [ruler["labelName"] for ruler in rulers] == ["Zone", "Zone"]
    assert annotations.read_bytes() == original


@pytest.mark.parametrize("across_maps", [False, True])
@pytest.mark.parametrize("painted_values", [[], [1]])
def test_report_flags_duplicate_names_with_empty_masks(
    tmp_path, across_maps, painted_values
):
    if across_maps:
        labelmaps = [
            save_labelmap(tmp_path, ["Zone"], filename="first.seg.nrrd",
                          painted_values=painted_values),
            save_labelmap(tmp_path, ["Zone"], filename="second.seg.nrrd", painted_values=[]),
        ]
    else:
        labelmaps = [save_labelmap(tmp_path, ["Zone", "Zone"], painted_values=painted_values)]
    annotations = save_annotations(
        tmp_path, [saved_ruler("Zone", 8), saved_ruler("Zone", 2, axis=1)]
    )
    original = annotations.read_bytes()

    row, = run_report(tmp_path, labelmaps, annotations)

    assert row["segment_name"] == "Zone"
    assert ruler_values(row) == ["8", "2"]
    assert "Multiple segmentation labels" in row["warnings"]
    assert "ambiguous" in row["warnings"]
    assert row["volume_mm3"] == ("36" if painted_values else "")
    assert row["labelmap_index"] == ("1" if painted_values else "")
    assert annotations.read_bytes() == original


def save_intensity_inputs(tmp_path, values, labelmaps):
    source = itk.image_from_array(np.asarray(values))
    source.SetSpacing([0.5, 2.0, 3.0])
    source.SetOrigin([1234.0, -4.0, 6.0])
    source.SetDirection(itk.matrix_from_array(np.array([
        [0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0],
    ])))
    itk.imwrite(source, str(tmp_path / "original-volume.nrrd"))
    paths = []
    for index, (labels, names) in enumerate(labelmaps):
        image = itk.image_from_array(np.asarray(labels, dtype=np.uint8))
        image.CopyInformation(source)
        path = tmp_path / f"labels-{index}.seg.nrrd"
        write_segmentation(image, path, [
            {"value": value, "name": name, "color": [255, 0, 0, 255]}
            for value, name in names.items()
        ])
        paths.append(path)
    return paths


def test_report_intensities_follow_voxels_across_maps_and_duplicate_names(tmp_path):
    source = np.array([
        [[-2.0, 100.0, 0.0], [40.0, 4.0, 6.0]],
        [[20.0, 80.0, 11.0], [150.0, 0.0, 999.0]],
    ])
    first = np.array([[[5, 0, 5], [0, 5, 5]], [[0, 0, 9], [0, 0, 0]]])
    second = np.array([[[0, 5, 0], [5, 0, 0]], [[5, 5, 9], [9, 0, 0]]])
    paths = save_intensity_inputs(tmp_path, source, [
        (first, {5: "shared", 9: "single"}),
        (second, {5: "shared", 9: "shared"}),
    ])
    annotations = save_annotations(tmp_path, [
        saved_ruler(name, length, axis=axis)
        for name in ("shared", "single", "outside")
        for length, axis in [(6, 0), (2, 1)]
    ])
    inputs = {path: path.read_bytes() for path in [
        *paths, annotations, tmp_path / "original-volume.nrrd",
    ]}

    rows = run_report(tmp_path, paths, annotations)

    assert [row["segment_name"] for row in rows] == [
        "shared", "single", "shared", "shared", "outside",
    ]
    assert [row["labelmap_index"] for row in rows] == ["1", "1", "2", "2", ""]
    assert [row["volume_mm3"] for row in rows] == ["12", "3", "12", "6", ""]
    expected = [
        (-2, 6, 2, 2, 10 ** 0.5, 8),
        (11, 11, 11, 11, 0, 11),
        (20, 100, 60, 60, 1000 ** 0.5, 240),
        (11, 150, 80.5, 80.5, 69.5, 161),
    ]
    for row, statistics in zip(rows, expected):
        assert [float(row[column]) for column in INTENSITY_COLUMNS] == pytest.approx(
            statistics, rel=1e-11,
        )
    assert rows[0]["intensity_stddev"] == "3.16227766017"
    for row in (rows[0], rows[2], rows[3]):
        assert ruler_values(row) == ["6", "2"]
        assert "ambiguous" in row["warnings"]
    assert ruler_values(rows[1]) == ["6", "2"]
    assert rows[1]["warnings"] == ""
    assert all(rows[-1][column] == "" for column in INTENSITY_COLUMNS)
    assert "No segmentation label matches" in rows[-1]["warnings"]
    assert all(path.read_bytes() == original for path, original in inputs.items())


@pytest.mark.parametrize("values,expected", [
    (np.array([30000, 30000, 30000, 30000], dtype=np.int16),
     (30000, 30000, 30000, 30000, 0, 120000)),
    (np.array([1e-12, 3e-12], dtype=np.float64),
     (1e-12, 3e-12, 2e-12, 2e-12, 1e-12, 4e-12)),
    (np.array([1.0, 2.0, 9.0]),
     (1, 9, 4, 2, (38 / 3) ** 0.5, 12)),
])
def test_report_intensities_preserve_numeric_range_and_precision(tmp_path, values, expected):
    source = values.reshape(1, 1, -1)
    paths = save_intensity_inputs(tmp_path, source, [(np.ones(source.shape), {1: "PET"})])

    row, = run_report(tmp_path, paths)

    assert [float(row[column]) for column in INTENSITY_COLUMNS] == pytest.approx(
        expected, rel=1e-11, abs=0,
    )


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -np.inf])
@pytest.mark.parametrize("selected", [False, True])
def test_report_nonfinite_intensities_are_confined_to_their_segment(tmp_path, invalid, selected):
    source = np.array([[[invalid, 2.0, 4.0, 100.0]]])
    labels = np.array([[[2 if selected else 0, 1, 1, 2 if selected else 0]]])
    paths = save_intensity_inputs(tmp_path, source, [(labels, {1: "valid", 2: "invalid"})])

    rows = run_report(tmp_path, paths)

    assert len(rows) == (2 if selected else 1)
    assert [float(rows[0][column]) for column in INTENSITY_COLUMNS] == [2, 4, 3, 3, 1, 6]
    assert "image values" not in rows[0]["warnings"]
    if selected:
        assert all(rows[1][column] == "" for column in INTENSITY_COLUMNS)
        assert "non-finite image values" in rows[1]["warnings"]
        assert rows[1]["volume_mm3"] == "6"


def test_report_blanks_all_intensities_if_a_reduction_overflows(tmp_path):
    source = np.array([[[1e308, 1e308]]])
    paths = save_intensity_inputs(tmp_path, source, [(np.ones(source.shape), {1: "large"})])

    row, = run_report(tmp_path, paths)

    assert all(row[column] == "" for column in INTENSITY_COLUMNS)
    assert "numeric range" in row["warnings"]
    assert row["volume_mm3"] == "6"


@pytest.mark.parametrize("mismatch", ["size", "origin", "spacing", "direction"])
def test_report_rejects_second_map_grid_mismatch_before_writing(tmp_path, mismatch):
    source = np.arange(24, dtype=np.float64).reshape(2, 3, 4)
    paths = save_intensity_inputs(tmp_path, source, [
        (np.ones(source.shape), {1: "first"}),
        (np.ones(source.shape), {1: "second"}),
    ])
    image = itk.imread(str(paths[1]))
    if mismatch == "size":
        resized = itk.image_from_array(np.ones((2, 3, 3), dtype=np.uint8))
        resized.CopyInformation(image)
        image = resized
    elif mismatch == "origin":
        image.SetOrigin([1234.001, -4.0, 6.0])
    elif mismatch == "spacing":
        image.SetSpacing([0.501, 2.0, 3.0])
    else:
        image.SetDirection(itk.matrix_from_array(np.eye(3)))
    itk.imwrite(image, str(paths[1]))
    output = tmp_path / "report.csv"
    original = b"existing report must survive failed validation\n"
    output.write_bytes(original)
    before_files = set(tmp_path.iterdir())

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "cli_list.py"), "ExportSegmentStatistics",
         str(tmp_path / "original-volume.nrrd"), ",".join(map(str, paths)), str(output)],
        cwd=REPO_ROOT, text=True, capture_output=True,
    )

    assert result.returncode != 0
    assert "same voxel grid" in result.stderr
    assert output.read_bytes() == original
    assert set(tmp_path.iterdir()) == before_files


def test_report_accepts_subtolerance_geometry_rounding(tmp_path):
    source = np.array([[[2.0, 4.0]]])
    paths = save_intensity_inputs(tmp_path, source, [(np.ones(source.shape), {1: "segment"})])
    image = itk.imread(str(paths[0]))
    image.SetOrigin([1234.000005, -4.0, 6.0])
    itk.imwrite(image, str(paths[0]))

    row, = run_report(tmp_path, paths)

    assert [float(row[column]) for column in INTENSITY_COLUMNS] == [2, 4, 3, 3, 1, 6]


@pytest.mark.parametrize("invalid_volume", ["2d", "vector"])
def test_report_rejects_nonscalar_or_nonvolume_underlay(tmp_path, invalid_volume):
    source = np.ones((2, 3, 4), dtype=np.float32)
    paths = save_intensity_inputs(tmp_path, source, [(source, {1: "segment"})])
    image = (itk.image_from_array(np.ones((3, 4), dtype=np.float32))
             if invalid_volume == "2d" else
             itk.image_from_array(np.ones((2, 3, 4, 3), dtype=np.float32), is_vector=True))
    itk.imwrite(image, str(tmp_path / "original-volume.nrrd"))
    output = tmp_path / "report.csv"

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "cli_list.py"), "ExportSegmentStatistics",
         str(tmp_path / "original-volume.nrrd"), str(paths[0]), str(output)],
        cwd=REPO_ROOT, text=True, capture_output=True,
    )

    assert result.returncode != 0
    assert "scalar 3-D images" in result.stderr
    assert not output.exists()


def test_report_intensities_apply_dicom_rescale_and_metadata_slice_order(tmp_path, dicom_fixtures):
    paths = sorted((dicom_fixtures / "dicom_rescale").glob("*.dcm"))
    assert len(paths) == 2
    labels = np.array([[[1, 0, 0], [0, 1, 0]], [[0, 1, 0], [0, 0, 1]]], dtype=np.uint8)
    image = itk.image_from_array(labels)
    image.SetSpacing([0.5, 2.0, 3.0])
    image.SetOrigin([10.0, 20.0, 30.0])
    labelmap = tmp_path / "PET.seg.nrrd"
    write_segmentation(image, labelmap, [{
        "value": 1, "name": "PET", "color": [255, 0, 0, 255],
    }])

    row, = run_report(tmp_path, [labelmap], volume=",".join(map(str, paths)))

    # Stored values 3, 23, 103, 123 become -8.75, -3.75, 16.25, 21.25.
    assert [float(row[column]) for column in INTENSITY_COLUMNS] == pytest.approx(
        [-8.75, 21.25, 6.25, 6.25, 162.5 ** 0.5, 25], rel=1e-11,
    )
    assert row["volume_mm3"] == "12"
