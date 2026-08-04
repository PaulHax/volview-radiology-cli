import json
import os

import pytest

from conftest import FIXTURES
from volview_cli_base.annotations import (
    load_annotations,
    read_annotations,
    write_annotations,
)

AXIAL_FRAME = {"planeNormal": [0, 0, 1], "planeOrigin": [0, 0, -12.5]}


def ruler(first, second, **fields):
    return dict(
        {"firstPoint": first, "secondPoint": second, "frameOfReference": AXIAL_FRAME},
        **fields
    )


def annotations_file(tools=None, labels=None):
    file = {"schemaVersion": 1, "space": "LPS", "tools": tools or {}}
    if labels is not None:
        file["labels"] = labels
    return file


# --------------------------------------------------------------------------
# Fail-closed validation
# --------------------------------------------------------------------------


def test_accepts_the_contract_shape():
    file = annotations_file(
        tools={
            "rulers": [ruler([-20, 0, -12.5], [20, 0, -12.5], labelName="lesion")],
            "rectangles": [ruler([-20, 0, -12.5], [20, 0, -12.5])],
            "polygons": [
                {
                    "points": [[0, 0, -12.5], [1, 0, -12.5], [1, 1, -12.5]],
                    "frameOfReference": AXIAL_FRAME,
                    "metadata": {"source": "reader-1"},
                }
            ],
        },
        labels={"rulers": {"lesion": {"color": "#ff0000", "strokeWidth": 2}}},
    )

    assert load_annotations(file) is file


@pytest.mark.parametrize(
    "file,message",
    [
        ("not an object", "must be a JSON object"),
        ({"space": "LPS", "tools": {}}, "unsupported schemaVersion"),
        (
            {"schemaVersion": 2, "space": "LPS", "tools": {}},
            "unsupported schemaVersion",
        ),
        ({"schemaVersion": 1, "space": "RAS", "tools": {}}, "unsupported space"),
        ({"schemaVersion": 1, "space": "LPS"}, "tools object"),
        (
            {"schemaVersion": 1, "space": "LPS", "labels": False, "tools": {}},
            "labels must be an object",
        ),
        (
            {"schemaVersion": 1, "space": "LPS", "labels": None, "tools": {}},
            "labels must be an object",
        ),
        (
            {"schemaVersion": 1, "space": "LPS", "tools": {"blobs": []}},
            "not a tool kind",
        ),
        (
            {"schemaVersion": 1, "space": "LPS", "tools": {"rulers": {}}},
            "must be an array",
        ),
    ],
)
def test_rejects_a_malformed_envelope(file, message):
    with pytest.raises(ValueError, match=message):
        load_annotations(file)


def test_rejects_a_ruler_without_a_frame_of_reference():
    file = annotations_file(
        tools={"rulers": [{"firstPoint": [0, 0, 0], "secondPoint": [1, 1, 1]}]}
    )

    with pytest.raises(ValueError, match=r"tools.rulers\[0\] is missing its frame"):
        load_annotations(file)


def test_accepts_a_scaled_nonzero_plane_normal():
    frame = {"planeNormal": [0, 0, 2], "planeOrigin": [0, 0, 0]}
    file = annotations_file(
        tools={
            "rulers": [
                {
                    "firstPoint": [0, 0, 0],
                    "secondPoint": [1, 1, 0],
                    "frameOfReference": frame,
                }
            ]
        }
    )

    assert load_annotations(file) is file


def test_rejects_an_extra_frame_of_reference_field():
    frame = dict(AXIAL_FRAME, coordinateSystem="LPS")
    file = annotations_file(
        tools={"rulers": [ruler([0, 0, 0], [1, 1, 0], frameOfReference=frame)]}
    )

    with pytest.raises(ValueError, match="frameOfReference carries unknown fields"):
        load_annotations(file)


def test_rejects_a_zero_plane_normal():
    frame = {"planeNormal": [0, 0, 0], "planeOrigin": [0, 0, 0]}
    file = annotations_file(
        tools={
            "rulers": [
                {
                    "firstPoint": [0, 0, 0],
                    "secondPoint": [1, 1, 0],
                    "frameOfReference": frame,
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="planeNormal must be a nonzero vector"):
        load_annotations(file)


def test_rejects_a_ruler_with_a_two_dimensional_point():
    file = annotations_file(
        tools={"rulers": [ruler([0, 0], [1, 1, 1])]},
    )

    with pytest.raises(ValueError, match=r"firstPoint must be three finite numbers"):
        load_annotations(file)


def test_rejects_a_polygon_with_fewer_than_three_points():
    file = annotations_file(
        tools={
            "polygons": [
                {
                    "points": [[0, 0, 0], [1, 0, 0]],
                    "frameOfReference": AXIAL_FRAME,
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="at least three points"):
        load_annotations(file)


def test_rejects_a_session_only_field_on_the_wire():
    file = annotations_file(
        tools={"rulers": [ruler([0, 0, 0], [1, 1, 1], id="ruler-1", color="#fff")]}
    )

    with pytest.raises(ValueError, match="may not ride on the wire: color, id"):
        load_annotations(file)


def test_rejects_a_dangling_label_reference():
    file = annotations_file(
        tools={"rulers": [ruler([0, 0, 0], [1, 1, 1], labelName="lesion")]},
        labels={"rectangles": {"lesion": {}}},
    )

    with pytest.raises(ValueError, match="labels.rulers does not declare"):
        load_annotations(file)


def test_an_unlabeled_tool_needs_no_label_namespace():
    assert load_annotations(
        annotations_file(tools={"rulers": [ruler([0, 0, 0], [1, 1, 1])]})
    )


@pytest.mark.parametrize(
    "fields,message",
    [
        ({"slice": "not-a-number"}, r"slice must be a finite number"),
        ({"slice": float("nan")}, r"slice must be a finite number"),
        ({"frame": 1.5}, r"frame must be a non-negative integer"),
        ({"frame": -1}, r"frame must be a non-negative integer"),
        ({"frame": True}, r"frame must be a non-negative integer"),
        ({"frame": float("inf")}, r"frame must be a non-negative integer"),
        ({"frame": 2**53}, r"frame must be a non-negative integer"),
        ({"labelName": None}, r"labelName must be a string"),
        ({"name": 123}, r"name must be a string"),
        ({"metadata": {"x": 3}}, r"metadata must be an object of string values"),
        ({"metadata": "notes"}, r"metadata must be an object of string values"),
    ],
)
def test_rejects_an_invalid_advisory_core_field(fields, message):
    file = annotations_file(tools={"rulers": [ruler([0, 0, 0], [1, 1, 1], **fields)]})

    with pytest.raises(ValueError, match=message):
        load_annotations(file)


def test_accepts_a_whole_valued_float_frame():
    # JSON has one number type, so 3.0 and 3 are the same wire value.
    file = annotations_file(tools={"rulers": [ruler([0, 0, 0], [1, 1, 1], frame=3.0)]})

    assert load_annotations(file) is file


@pytest.mark.parametrize(
    "definition,message",
    [
        (False, r"must be an object"),
        ({"opacity": 0.5}, r"carries unknown fields: opacity"),
        ({"color": 123}, r"color must be a string"),
        ({"fillColor": 123}, r"fillColor must be a string"),
        ({"strokeWidth": "2"}, r"strokeWidth must be a finite number"),
        ({"strokeWidth": float("inf")}, r"strokeWidth must be a finite number"),
    ],
)
def test_rejects_an_invalid_label_definition(definition, message):
    file = annotations_file(tools={}, labels={"rulers": {"lesion": definition}})

    with pytest.raises(ValueError, match=message):
        load_annotations(file)


def test_rejects_reserved_label_and_metadata_keys():
    labels = {"rulers": json.loads('{"__proto__": {}}')}
    with pytest.raises(ValueError, match="reserved label name"):
        load_annotations(annotations_file(tools={}, labels=labels))

    metadata = json.loads('{"__proto__": "value"}')
    file = annotations_file(
        tools={"rulers": [ruler([0, 0, 0], [1, 1, 0], metadata=metadata)]}
    )
    with pytest.raises(ValueError, match="metadata must be an object"):
        load_annotations(file)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_rejects_a_non_finite_coordinate(bad):
    file = annotations_file(tools={"rulers": [ruler([bad, 0, 0], [1, 1, 1])]})

    with pytest.raises(ValueError, match="three finite numbers"):
        load_annotations(file)


# --------------------------------------------------------------------------
# Round trip
# --------------------------------------------------------------------------


def test_round_trip_through_disk(tmp_path):
    source = annotations_file(
        tools={"rulers": [ruler([-20, 0, -12.5], [20, 0, -12.5])]}
    )
    output = tmp_path / "nested" / "out.annotations.json"

    write_annotations(source, output)

    result = read_annotations(output)
    assert result == source


def test_writing_an_invalid_file_fails_before_the_write(tmp_path):
    output = tmp_path / "out.annotations.json"

    with pytest.raises(ValueError, match="unsupported space"):
        write_annotations({"schemaVersion": 1, "space": "RAS", "tools": {}}, output)

    assert not output.exists()


def test_writing_a_nan_fails_before_the_write(tmp_path):
    # Label style values are deliberately lax, so a NaN can reach
    # serialization — which must refuse it (JSON.parse rejects the literal)
    # before any partial file appears.
    output = tmp_path / "out.annotations.json"
    file = annotations_file(
        tools={"rulers": []},
        labels={"rulers": {"lesion": {"strokeWidth": float("nan")}}},
    )

    with pytest.raises(ValueError):
        write_annotations(file, output)

    assert not output.exists()


def test_reads_the_published_interchange_example():
    # A copy of the VolView package's worked example,
    # backend-contract/fixtures/wire/annotations-file.json: one ruler, one
    # rectangle, one polygon, per-kind labels reusing a name, and tool metadata.
    example = read_annotations(
        os.path.join(FIXTURES, "annotations", "interchange-example.annotations.json")
    )

    assert set(example["tools"]) == {"rulers", "rectangles", "polygons"}
    assert load_annotations(example) is example
