import numpy as np
import pytest

itk = pytest.importorskip("itk")

from volview_cli_base.roi_report import image_metadata, report_rows  # noqa: E402
from volview_cli_base.segnrrd import write_segmentation  # noqa: E402


def test_embedded_segment_name_and_spacing_round_trip(tmp_path):
    labels = np.array([[[0, 4], [4, 4]]], dtype=np.uint8)
    image = itk.image_from_array(labels)
    image.SetSpacing([0.5, 2.0, 3.0])
    path = tmp_path / "regions.seg.nrrd"
    write_segmentation(
        image,
        path,
        [{"value": 4, "name": "Reviewed region", "color": [20, 40, 60, 255]}],
    )

    restored = itk.imread(path)
    rows = report_rows(
        itk.array_view_from_image(restored),
        restored.GetSpacing(),
        image_metadata(restored),
    )

    assert len(rows) == 1
    assert rows[0]["region_of_interest"] == "Reviewed region"
    assert rows[0]["label_value"] == "4"
    assert rows[0]["voxel_count"] == "3"
    assert rows[0]["volume_mm3"] == "9"
