import numpy as np
import pytest

from volview_cli_base.roi_report import segment_names, voxel_summary


def test_segment_names_read_slicer_metadata():
    metadata = {
        "Segment0_LabelValue": "3",
        "Segment0_Name": "Left region",
        "Segment1_LabelValue": "7",
        "Segment1_Name": "Right region",
        "unrelated": "ignored",
    }
    assert segment_names(metadata) == {3: "Left region", 7: "Right region"}


def test_voxel_summary_counts_regions_and_voxel_volume():
    labels = np.array(
        [
            [[0, 1], [1, 2]],
            [[0, 0], [2, 2]],
        ],
        dtype=np.uint8,
    )

    counts, voxel_volume = voxel_summary(labels, spacing=[0.5, 2.0, 3.0])

    assert counts == {1: 2, 2: 3}
    assert voxel_volume == 3.0


def test_voxel_summary_ignores_background():
    counts, _ = voxel_summary(np.zeros((2, 2), dtype=np.uint8), [1, 1])
    assert counts == {}


def test_voxel_summary_rejects_non_integer_image():
    with pytest.raises(ValueError, match="integer pixel type"):
        voxel_summary(np.array([0.0, 1.0]), spacing=[1.0])


def test_voxel_summary_rejects_mismatched_spacing():
    with pytest.raises(ValueError, match="does not match spacing"):
        voxel_summary(np.zeros((2, 2), dtype=np.uint8), spacing=[1.0, 1.0, 1.0])
