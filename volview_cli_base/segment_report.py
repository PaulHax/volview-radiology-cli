"""Segment names, volumes, and source-image intensity statistics."""

import math
import re

INTENSITY_COLUMNS = (
    "intensity_min", "intensity_max", "intensity_mean",
    "intensity_median", "intensity_stddev", "intensity_sum",
)
PET_INTENSITY_COLUMNS = tuple("pet_" + column for column in INTENSITY_COLUMNS)

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
    return {
        value: _sample_statistics(source[labels == value], INTENSITY_COLUMNS)
        for value in label_values
    }


def _sample_statistics(samples, columns, source_name="Image"):
    """Format finite intensity reductions, preserving a warning on failure."""
    import numpy as np

    samples = np.asarray(samples, dtype=np.float64)
    if not np.isfinite(samples).all():
        return {}, (
            "Segment contains non-finite %s values; intensity statistics unavailable."
            % ("image" if source_name == "Image" else source_name)
        )
    with np.errstate(over="ignore", invalid="ignore"):
        statistics = (
            np.min(samples), np.max(samples), np.mean(samples),
            np.median(samples), np.std(samples), np.sum(samples),
        )
    if not np.isfinite(statistics).all():
        return {}, (
            "%s statistics exceed the numeric range; intensity statistics unavailable."
            % source_name
        )
    return {
        column: format(float(number), ".12g")
        for column, number in zip(columns, statistics)
    }, ""


def _pet_samples(pet, labelmap, indices):
    """Linearly sample PET at label voxel centers inside its voxel-center extent."""
    from itertools import product

    import itk
    import numpy as np

    label_direction = itk.array_from_matrix(labelmap.GetDirection())
    pet_direction = itk.array_from_matrix(pet.GetDirection())
    points = (
        (indices[:, ::-1] * np.asarray(labelmap.GetSpacing())) @ label_direction.T
        + np.asarray(labelmap.GetOrigin())
    )
    positions = (
        (points - np.asarray(pet.GetOrigin())) @ np.linalg.inv(pet_direction).T
        / np.asarray(pet.GetSpacing())
    )
    maximum = np.asarray(pet.GetLargestPossibleRegion().GetSize()) - 1
    covered = np.all((positions >= -1e-5) & (positions <= maximum + 1e-5), axis=1)
    positions = np.clip(positions[covered], 0, maximum)
    rounded = np.rint(positions)
    positions = np.where(np.abs(positions - rounded) <= 1e-10, rounded, positions)
    lower = np.floor(positions).astype(np.int64)
    upper = np.minimum(lower + 1, maximum)
    fraction = positions - lower
    source = itk.array_view_from_image(pet)
    samples = np.zeros(len(positions), dtype=np.float64)
    for corner in product((0, 1), repeat=3):
        index = np.where(corner, upper, lower)
        weight = np.prod(np.where(corner, fraction, 1 - fraction), axis=1)
        selected = weight > 0
        x, y, z = index[selected].T
        # Zero-weight neighbors do not contribute, even if their voxels are NaN.
        with np.errstate(over="ignore", invalid="ignore"):
            samples[selected] += source[z, y, x].astype(np.float64) * weight[selected]
    return samples, int(np.count_nonzero(~covered))


def pet_segment_intensities(pet, labelmap, voxel_counts):
    """Summarize PET on each segment's physical grid without zero padding."""
    import itk
    import numpy as np

    if pet.GetImageDimension() != 3 or pet.GetNumberOfComponentsPerPixel() != 1:
        raise ValueError("PET volume must be a scalar 3-D image")
    labels = itk.array_view_from_image(labelmap)
    flat_labels = labels.reshape(-1)
    summaries = {}
    for value, voxel_count in voxel_counts.items():
        samples = np.empty(voxel_count, dtype=np.float64)
        sample_count, outside = 0, 0
        # Bound coordinate arrays while retaining samples for the exact median.
        for start in range(0, flat_labels.size, 65536):
            indices = np.flatnonzero(flat_labels[start:start + 65536] == value) + start
            if not len(indices):
                continue
            coordinates = np.column_stack(np.unravel_index(indices, labels.shape))
            batch, batch_outside = _pet_samples(pet, labelmap, coordinates)
            samples[sample_count:sample_count + len(batch)] = batch
            sample_count += len(batch)
            outside += batch_outside
        samples = samples[:sample_count]
        warnings = []
        if outside:
            warnings.append(
                "%d of %d segment voxel centers are outside the PET volume; "
                "PET statistics use only covered voxels." % (outside, voxel_count)
                if len(samples) else
                "Segment is outside the PET volume; PET intensity statistics unavailable."
            )
        statistics, warning = (
            _sample_statistics(samples, PET_INTENSITY_COLUMNS, "PET")
            if len(samples) else ({}, "")
        )
        if warning:
            warnings.append(warning)
        summaries[value] = statistics, " ".join(warnings)
    return summaries
