import csv

import numpy as np
import pytest

from volview_cli_base.roi_report import report_rows, segment_names, write_csv


def test_segment_names_read_slicer_metadata():
    metadata = {
        "Segment0_LabelValue": "3",
        "Segment0_Name": "Left region",
        "Segment1_LabelValue": "7",
        "Segment1_Name": "Right region",
        "unrelated": "ignored",
    }
    assert segment_names(metadata) == {3: "Left region", 7: "Right region"}


def test_report_counts_regions_and_physical_volume():
    labels = np.array(
        [
            [[0, 1], [1, 2]],
            [[0, 0], [2, 2]],
        ],
        dtype=np.uint8,
    )
    metadata = {
        "Segment0_LabelValue": "1",
        "Segment0_Name": "First region",
    }

    rows = report_rows(labels, spacing=[0.5, 2.0, 3.0], metadata=metadata)

    assert rows == [
        {
            "region_of_interest": "First region",
            "label_value": "1",
            "voxel_count": "2",
            "voxel_volume_mm3": "3",
            "volume_mm3": "6",
            "volume_ml": "0.006",
        },
        {
            "region_of_interest": "Region 2",
            "label_value": "2",
            "voxel_count": "3",
            "voxel_volume_mm3": "3",
            "volume_mm3": "9",
            "volume_ml": "0.009",
        },
    ]


def test_report_rejects_non_integer_image():
    with pytest.raises(ValueError, match="integer pixel type"):
        report_rows(np.array([0.0, 1.0]), spacing=[1.0])


def test_empty_label_map_writes_header_only(tmp_path):
    output = tmp_path / "nested" / "report.csv"
    write_csv(report_rows(np.zeros((2, 2), dtype=np.uint8), [1, 1]), output)

    with output.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    assert rows == [[
        "region_of_interest",
        "label_value",
        "voxel_count",
        "voxel_volume_mm3",
        "volume_mm3",
        "volume_ml",
    ]]
