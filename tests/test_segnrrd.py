"""Tests for embedded ``.seg.nrrd`` metadata serialization.

``build_seg_metadata`` is the CLI half of the segment-metadata round-trip; the
client half is VolView's ``parseSegNrrdMetadata`` (``src/io/segNrrdMetadata.ts``,
covered by ``segNrrdMetadata.spec.ts``). These tests verify the corresponding
Slicer-convention ``Segment{N}_*`` header keys and values.
"""
from volview_cli_base.segnrrd import build_seg_metadata, _color_string


# A two-segment descriptor list (the Otsu shape) over a 4x5x6 labelmap.
_DESCRIPTORS = [
    {"value": 1, "name": "Region 1 (lowest)", "color": [231, 76, 60, 255]},
    {"value": 2, "name": "Region 2", "color": [46, 204, 113, 255]},
]
_DIMS = (4, 5, 6)


def test_color_string_is_six_decimal_space_joined_0_1_floats():
    # Slicer stores colors as space-joined 0-1 floats with 6 decimals.
    assert _color_string([231, 76, 60]) == "0.905882 0.298039 0.235294"
    assert _color_string([0, 0, 0]) == "0.000000 0.000000 0.000000"
    assert _color_string([255, 255, 255]) == "1.000000 1.000000 1.000000"


def test_color_string_ignores_alpha():
    # A 4th (alpha) channel is not serialized — only R G B travel in the header.
    assert _color_string([231, 76, 60, 128]) == _color_string([231, 76, 60])


def test_color_round_trips_through_the_client_parser_math():
    # parseSegNrrdMetadata inverts the color as round(float(part) * 255); the
    # 6-decimal write must recover every original 0-255 channel exactly.
    for channel in (0, 1, 46, 76, 127, 128, 204, 231, 254, 255):
        part = _color_string([channel, channel, channel]).split()[0]
        assert round(float(part) * 255) == channel


def test_segment_fields_use_zero_based_index_and_voxel_label_value():
    meta = build_seg_metadata(_DESCRIPTORS, _DIMS)
    # Segment{N} is the 0-based enumeration index...
    assert meta["Segment0_Name"] == "Region 1 (lowest)"
    assert meta["Segment1_Name"] == "Region 2"
    # ...while LabelValue / ID carry the actual voxel value.
    assert meta["Segment0_LabelValue"] == "1"
    assert meta["Segment1_LabelValue"] == "2"
    assert meta["Segment0_ID"] == "Segment_1"
    assert meta["Segment1_ID"] == "Segment_2"


def test_segment_color_and_constant_fields():
    meta = build_seg_metadata(_DESCRIPTORS, _DIMS)
    assert meta["Segment0_Color"] == "0.905882 0.298039 0.235294"
    assert meta["Segment1_Color"] == "0.180392 0.800000 0.443137"
    for index in (0, 1):
        assert meta["Segment%d_Layer" % index] == "0"
        assert meta["Segment%d_Tags" % index] == "|"


def test_extent_spans_dimensions_minus_one():
    meta = build_seg_metadata(_DESCRIPTORS, _DIMS)
    # "0 x-1 0 y-1 0 z-1" for a 4x5x6 labelmap.
    assert meta["Segment0_Extent"] == "0 3 0 4 0 5"
    assert meta["Segment1_Extent"] == meta["Segment0_Extent"]


def test_segmentation_header_block():
    meta = build_seg_metadata(_DESCRIPTORS, _DIMS)
    assert meta["Segmentation_MasterRepresentation"] == "Binary labelmap"
    assert meta["Segmentation_ContainedRepresentationNames"] == "Binary labelmap|"
    assert meta["Segmentation_ReferenceImageExtentOffset"] == "0 0 0"


def test_single_segment_threshold_shape():
    # The Threshold CLI emits exactly one segment.
    meta = build_seg_metadata(
        [{"value": 1, "name": "50 – 65535", "color": [255, 0, 0, 255]}],
        (2, 2, 2),
    )
    assert meta["Segment0_Name"] == "50 – 65535"
    assert meta["Segment0_Color"] == "1.000000 0.000000 0.000000"
    assert "Segment1_Name" not in meta
