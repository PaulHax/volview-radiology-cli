"""Segment names, volumes, and source-image intensity statistics."""

import math
import re

INTENSITY_COLUMNS = (
    "intensity_min", "intensity_max", "intensity_mean",
    "intensity_median", "intensity_stddev", "intensity_sum",
)

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


def segment_intensities(underlay, labelmap, label_values):
    """Summarize source voxels by label value on a matching physical grid."""
    import itk
    import numpy as np

    if any(
        image.GetImageDimension() != 3 or image.GetNumberOfComponentsPerPixel() != 1
        for image in (underlay, labelmap)
    ):
        raise ValueError("input volume and label maps must be scalar 3-D images")
    same_size = tuple(underlay.GetLargestPossibleRegion().GetSize()) == tuple(
        labelmap.GetLargestPossibleRegion().GetSize()
    )
    same_geometry = all(np.allclose(left, right, rtol=0, atol=1e-5) for left, right in (
        (underlay.GetOrigin(), labelmap.GetOrigin()),
        (underlay.GetSpacing(), labelmap.GetSpacing()),
        (itk.array_from_matrix(underlay.GetDirection()),
         itk.array_from_matrix(labelmap.GetDirection())),
    ))
    if not same_size or not same_geometry:
        raise ValueError(
            "input volume and label map must share the same voxel grid "
            "(size, origin, spacing, and direction); resample the segmentation "
            "to the input volume before exporting statistics"
        )

    source = itk.array_view_from_image(underlay)
    labels = itk.array_view_from_image(labelmap)
    summaries = {}
    for value in label_values:
        samples = source[labels == value].astype(np.float64)
        if not np.isfinite(samples).all():
            summaries[value] = (
                {}, "Segment contains non-finite image values; "
                "intensity statistics unavailable."
            )
            continue
        with np.errstate(over="ignore", invalid="ignore"):
            statistics = (
                np.min(samples), np.max(samples), np.mean(samples),
                np.median(samples), np.std(samples), np.sum(samples),
            )
        if not np.isfinite(statistics).all():
            summaries[value] = (
                {}, "Image statistics exceed the numeric range; "
                "intensity statistics unavailable."
            )
            continue
        summaries[value] = (
            {column: format(float(number), ".12g")
             for column, number in zip(INTENSITY_COLUMNS, statistics)},
            "",
        )
    return summaries
