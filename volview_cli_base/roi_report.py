"""Measurements for the nonzero regions in a scalar label map."""

import csv
import math
import os
import re


CSV_COLUMNS = (
    "region_of_interest",
    "label_value",
    "voxel_count",
    "voxel_volume_mm3",
    "volume_mm3",
    "volume_ml",
)

_SEGMENT_FIELD = re.compile(r"^Segment(\d+)_(LabelValue|Name)$")


def _format_float(value):
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def segment_names(metadata):
    """Return ``label value -> name`` from Slicer ``.seg.nrrd`` metadata."""
    segments = {}
    for key, value in (metadata or {}).items():
        match = _SEGMENT_FIELD.match(str(key))
        if not match:
            continue
        index, field = match.groups()
        segments.setdefault(index, {})[field] = str(value)

    names = {}
    for segment in segments.values():
        try:
            label_value = int(segment["LabelValue"])
        except (KeyError, TypeError, ValueError):
            continue
        name = segment.get("Name", "").strip()
        if name:
            names[label_value] = name
    return names


def report_rows(label_array, spacing, metadata=None):
    """Describe each nonzero integer value in ``label_array``.

    ``spacing`` is in millimetres and follows the image axes. The array may use
    the reverse storage-axis order; voxel volume is invariant to axis order.
    """
    import numpy as np

    array = np.asarray(label_array)
    if not np.issubdtype(array.dtype, np.integer):
        raise ValueError("input label map must have an integer pixel type")

    spacings = [abs(float(value)) for value in spacing]
    if len(spacings) != array.ndim:
        raise ValueError(
            "label map dimension does not match spacing: %d dimensions, %d values"
            % (array.ndim, len(spacings))
        )
    voxel_volume = math.prod(spacings)
    names = segment_names(metadata)
    values, counts = np.unique(array, return_counts=True)

    rows = []
    for raw_value, raw_count in zip(values, counts):
        value = int(raw_value)
        if value == 0:
            continue
        count = int(raw_count)
        volume = count * voxel_volume
        rows.append(
            {
                "region_of_interest": names.get(value, f"Region {value}"),
                "label_value": str(value),
                "voxel_count": str(count),
                "voxel_volume_mm3": _format_float(voxel_volume),
                "volume_mm3": _format_float(volume),
                "volume_ml": _format_float(volume / 1000.0),
            }
        )
    return rows


def write_csv(rows, output_path):
    """Write report rows to ``output_path``, including the header when empty."""
    parent = os.path.dirname(str(output_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def image_metadata(image):
    """Convert an ITK image metadata dictionary to ordinary strings."""
    dictionary = image.GetMetaDataDictionary()
    keys = (
        dictionary.GetKeys()
        if hasattr(dictionary, "GetKeys")
        else dictionary.keys()
    )
    return {str(key): str(dictionary[key]) for key in keys}
