"""What a scalar label map says about its regions, before any annotation.

The names and voxel volumes here are the half of the region report that needs
only the label map. ``roi_rulers`` joins them to the rulers on the image and
owns the CSV; keeping the two apart lets the volume half be tested without any
annotation input.
"""

import math
import re

_SEGMENT_FIELD = re.compile(r"^Segment(\d+)_(LabelValue|Name)$")


def format_float(value):
    """A CSV number: six decimals with trailing zeros trimmed."""
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


def voxel_summary(label_array, spacing):
    """``(voxel counts by nonzero label value, one voxel's volume in mm^3)``.

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

    values, counts = np.unique(array, return_counts=True)
    counts_by_value = {
        int(value): int(count)
        for value, count in zip(values, counts)
        if int(value) != 0
    }
    return counts_by_value, math.prod(spacings)


def image_metadata(image):
    """Convert an ITK image metadata dictionary to ordinary strings."""
    from volview_cli_base.assemble import dictionary_keys

    dictionary = image.GetMetaDataDictionary()
    keys = dictionary_keys(dictionary)
    return {str(key): str(dictionary[key]) for key in keys}
