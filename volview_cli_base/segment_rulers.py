"""Generate segment diameters and report saved rulers in world millimetres."""

import math
from collections import Counter

from volview_cli_base.annotations import SCHEMA_VERSION, SPACE
from volview_cli_base.paths import ensure_parent_directory
from volview_cli_base.segment_report import INTENSITY_COLUMNS, format_float, segment_names

LD = "LD"
SAD = "SAD"
MEASUREMENT_KINDS = (LD, SAD)

CSV_COLUMNS = (
    "input_image_path",
    "segment_name",
    "labelmap_index",
    "volume_mm3",
    "warnings",
    *INTENSITY_COLUMNS,
)


# ---------------------------------------------------------------------------
# Labelmap inputs
# ---------------------------------------------------------------------------


def reject_multi_file_dicom_series(paths):
    """Raise when two or more of ``paths`` belong to the same DICOM series.

    Each labelmap file is measured as its own complete label map (see the
    README's "Segment jobs" limitations): a multi-file DICOM
    series given as the labelmap input would silently become one one-slice
    labelmap per file instead of the intended volume, so this fails closed
    rather than measure a fraction of the series. A single DICOM file is
    unaffected -- it is already read whole by ``assemble``.

    A file whose ``SeriesInstanceUID`` can't be read is excluded from series
    grouping rather than failing closed, so a same-series pair with one
    unreadable member could still slip through.
    """
    if len(paths) < 2:
        return

    from volview_cli_base.assemble import dicom_series_uid, is_dicom

    files_by_series = {}
    for path in paths:
        if not is_dicom(path):
            continue
        series_uid = dicom_series_uid(path)
        if series_uid:
            files_by_series.setdefault(series_uid, []).append(path)

    conflict = next(
        (files for files in files_by_series.values() if len(files) > 1), None
    )
    if conflict is None:
        return
    raise ValueError(
        "%d label map input files belong to the same DICOM series; each "
        "labelmap input file is treated as one complete label map, so a "
        "multi-file DICOM series is not supported for the labelmap input -- "
        "use a single-file format such as .seg.nrrd instead. Files: %s"
        % (len(conflict), ", ".join(conflict))
    )


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


def ruler_label(ruler):
    """The name to audit by: the shared ``labelName``, else the per-tool ``name``."""
    return str(ruler.get("labelName") or ruler.get("name") or "")


def index_existing_rulers(annotations):
    """Group rulers by their literal segment name."""
    by_segment = {}
    for ruler in ((annotations or {}).get("tools") or {}).get("rulers") or []:
        by_segment.setdefault(ruler_label(ruler).strip(), []).append(ruler)
    return by_segment


def ruler_length_mm(ruler):
    """A ruler's world length in millimetres, or ``None`` for invalid endpoints."""
    first = ruler.get("firstPoint") or []
    second = ruler.get("secondPoint") or []
    if len(first) != 3 or len(second) != 3:
        return None
    try:
        length = math.hypot(*(float(a) - float(b) for a, b in zip(first, second)))
    except (TypeError, ValueError):
        return None
    return length if math.isfinite(length) else None


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def axial_image_axis(direction):
    """The image axis whose direction is nearest to the LPS superior axis.

    ``direction`` is the 3x3 matrix whose column ``j`` is image axis ``j``'s
    unit direction in LPS, so row 2 holds each axis' superior component.
    """
    return max(range(3), key=lambda axis: abs(float(direction[2][axis])))


def _hull_candidates(rows, columns):
    """The per-row extreme points, a superset of the convex hull's vertices.

    A point strictly between two others in its own row lies inside their
    segment, so it can never be an extreme point in any direction. Keeping only
    each row's first and last column preserves the longest chord's endpoints
    while bounding the pairwise search to two points per row.
    """
    import numpy as np

    order = np.lexsort((columns, rows))
    ordered_rows = rows[order]
    first_in_row = np.empty(ordered_rows.shape, dtype=bool)
    first_in_row[0] = True
    first_in_row[1:] = ordered_rows[1:] != ordered_rows[:-1]
    # Each row's last point is the one before the next row's first, and the
    # final point is always a last -- exactly what rolling left produces.
    keep = order[first_in_row | np.roll(first_in_row, -1)]
    return rows[keep], columns[keep]


def _longest_chord(points_mm):
    """The farthest-apart pair in ``points_mm``: ``(length, (index, index))``."""
    import numpy as np

    deltas = points_mm[:, None, :] - points_mm[None, :, :]
    distances = np.sqrt((deltas**2).sum(axis=-1))
    first, second = np.unravel_index(int(np.argmax(distances)), distances.shape)
    return float(distances[first, second]), (int(first), int(second))


def _perpendicular_extent(points_mm, start_mm, end_mm, step_mm):
    """The widest extent perpendicular to ``start_mm``->``end_mm``, and its ends.

    The segment is swept in bins along the long axis and the widest bin wins, so
    the reported short axis is the segment's widest span across its longest
    diameter rather than a chord through the centroid. The endpoints are real
    foreground points, though on a concave segment the segment between them can
    leave the mask, and are ``None`` when no bin holds two points.
    """
    import numpy as np

    direction = end_mm - start_mm
    length = float(np.linalg.norm(direction))
    if length == 0:
        return 0.0, None

    along_axis = direction / length
    across_axis = np.array([-along_axis[1], along_axis[0]])
    relative = points_mm - start_mm
    along = relative @ along_axis
    across = relative @ across_axis

    bin_count = max(1, int(math.ceil(length / step_mm)))
    bins = np.clip((along * bin_count / length).astype(int), 0, bin_count - 1)

    widest = 0.0
    endpoints = None
    for index in range(bin_count):
        members = np.flatnonzero(bins == index)
        if members.size < 2:
            continue
        values = across[members]
        extent = float(values.max() - values.min())
        if extent > widest:
            widest = extent
            endpoints = (
                int(members[int(np.argmin(values))]),
                int(members[int(np.argmax(values))]),
            )
    return widest, endpoints


def _mask_points(rows, columns, endpoints):
    """The two ``(row, column)`` mask indices ``endpoints`` names, or ``None``."""
    if endpoints is None:
        return None
    return tuple((int(rows[index]), int(columns[index])) for index in endpoints)


def measure_slice(mask, spacing_mm):
    """LD and SAD for one in-plane boolean ``mask``.

    ``spacing_mm`` is the millimetre spacing of the mask's two axes. Returns
    ``None`` for a mask that cannot span a chord, else a dict carrying the two
    lengths and each measurement's endpoint indices into the mask.
    """
    import numpy as np

    rows, columns = np.nonzero(mask)
    if rows.size < 2:
        return None

    row_spacing, column_spacing = (abs(float(value)) for value in spacing_mm)
    hull_rows, hull_columns = _hull_candidates(rows, columns)
    hull_mm = np.column_stack([hull_rows * row_spacing, hull_columns * column_spacing])
    ld_mm, ld_endpoints = _longest_chord(hull_mm)

    points_mm = np.column_stack([rows * row_spacing, columns * column_spacing])
    sad_mm, sad_endpoints = _perpendicular_extent(
        points_mm,
        hull_mm[ld_endpoints[0]],
        hull_mm[ld_endpoints[1]],
        step_mm=min(row_spacing, column_spacing) * 0.5,
    )

    return {
        "ld_mm": ld_mm,
        "sad_mm": sad_mm,
        "ld_points": _mask_points(hull_rows, hull_columns, ld_endpoints),
        "sad_points": _mask_points(rows, columns, sad_endpoints),
    }


def measure_label(array, value, slice_axis, in_plane_spacing_mm):
    """Measure one label value across every slice, keeping the widest.

    ``array`` is the label map in storage order, ``slice_axis`` the array axis
    the slices stack along, and ``in_plane_spacing_mm`` the spacing of the two
    remaining array axes in their natural order. Returns the winning slice's
    measurement plus its ``slice`` index, or ``None`` when the label is absent
    or too small to span a chord.
    """
    import numpy as np

    mask_volume = np.asarray(array) == value
    best = None
    for index in range(mask_volume.shape[slice_axis]):
        measurement = measure_slice(
            np.take(mask_volume, index, axis=slice_axis), in_plane_spacing_mm
        )
        if measurement is None:
            continue
        if best is None or measurement["ld_mm"] > best["ld_mm"]:
            best = dict(measurement, slice=index)
    return best


# ---------------------------------------------------------------------------
# Voxel indices to world points
# ---------------------------------------------------------------------------


def slice_axis_and_spacing(labelmap):
    """``(array slice axis, in-plane spacing, in-plane array axes)``.

    The image axis nearest to superior-inferior carries the axial slices. An
    ``itk`` array is stored with its axes reversed, so image axis ``a`` is
    array axis ``2 - a``; the two remaining array axes, in their own ascending
    order, are the ones a slice's rows and columns index.
    """
    import itk

    direction = itk.array_from_matrix(labelmap.GetDirection())
    slice_axis = 2 - axial_image_axis(direction)
    spacing = [abs(float(value)) for value in labelmap.GetSpacing()]
    in_plane_axes = [axis for axis in range(3) if axis != slice_axis]
    return slice_axis, [spacing[2 - axis] for axis in in_plane_axes], in_plane_axes


def world_point(labelmap, array_index):
    """The LPS millimetre point at a ``(k, j, i)`` array index."""
    point = labelmap.TransformIndexToPhysicalPoint(
        [int(value) for value in reversed(array_index)]
    )
    return [float(value) for value in point]


def _array_index(slice_axis, slice_index, in_plane_axes=(), in_plane=()):
    """A ``(k, j, i)`` index on ``slice_index``, at the origin off the named axes."""
    index = [0, 0, 0]
    index[slice_axis] = slice_index
    for axis, position in zip(in_plane_axes, in_plane):
        index[axis] = position
    return index


def frame_of_reference(labelmap, slice_axis, slice_index):
    """The plane a generated ruler sits in, aligned to an image axis.

    ``planeNormal`` is the slice axis' own direction, so the plane is never
    oblique to the image; ``planeOrigin`` is a point on that slice.
    """
    import itk

    direction = itk.array_from_matrix(labelmap.GetDirection())
    image_axis = 2 - slice_axis
    return {
        "planeNormal": [float(direction[row][image_axis]) for row in range(3)],
        "planeOrigin": world_point(labelmap, _array_index(slice_axis, slice_index)),
    }


def generated_ruler(labelmap, slice_axis, in_plane_axes, measurement, kind, label):
    """One ruler for ``kind``, or ``None`` when that measurement has no points."""
    points = measurement[kind.lower() + "_points"]
    if not points:
        return None

    slice_index = measurement["slice"]
    indices = [
        _array_index(slice_axis, slice_index, in_plane_axes, point) for point in points
    ]
    first, second = (world_point(labelmap, index) for index in indices)
    return {
        "firstPoint": first,
        "secondPoint": second,
        "frameOfReference": frame_of_reference(labelmap, slice_axis, slice_index),
        "labelName": label,
        "name": label,
        "slice": slice_index,
    }


def build_output_annotations(rulers, input_annotations):
    """The additive result: only the rulers this run generated.

    A label the input file already defines keeps its own style, so a re-run
    never restyles an annotator's labels.
    """
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "space": SPACE,
        "tools": {"rulers": rulers},
    }
    if not rulers:
        return result
    defined = ((input_annotations or {}).get("labels") or {}).get("rulers") or {}
    result["labels"] = {
        "rulers": {
            ruler["labelName"]: dict(defined.get(ruler["labelName"], {}))
            for ruler in rulers
            if ruler.get("labelName")
        }
    }
    return result


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _report_row(input_image_path, segment_name, labelmap_index=None):
    """A blank report row, ready for whichever cells the caller fills in."""
    row = dict.fromkeys(CSV_COLUMNS, "")
    row["input_image_path"] = input_image_path
    row["segment_name"] = segment_name
    if labelmap_index is not None:
        row["labelmap_index"] = labelmap_index
    return row


def labelmap_segments(metadata, present_values):
    """``[(segment name, label value)]`` for a label map's painted segments."""
    names = segment_names(metadata)
    return [
        (names.get(value, "Segment %d" % value), value)
        for value in sorted(present_values)
    ]


def _ruler_measurements(rulers):
    """Number saved lengths longest first, retaining invalid rulers as blanks."""
    lengths = [ruler_length_mm(ruler) for ruler in rulers]
    available = sorted((length for length in lengths if length is not None), reverse=True)
    values = {
        "ruler_%d_length_mm" % index: (
            format_float(length) if length is not None else ""
        )
        for index, length in enumerate(
            available + [None] * (len(rulers) - len(available)), start=1
        )
    }
    warnings = []
    if not rulers:
        warnings.append("No rulers are assigned to this segmentation label.")
    if any(length is None or length <= 0 for length in lengths):
        warnings.append("One or more rulers have no positive finite length.")
    return values, warnings


def segment_rows(
    input_image_path,
    segments,
    existing,
    voxel_counts,
    voxel_volume_mm3,
    segment_name_counts=None,
    labelmap_index=None,
    intensity_stats=None,
):
    """Join saved rulers to painted segments."""
    name_counts = (
        segment_name_counts
        if segment_name_counts is not None
        else Counter(name for name, _ in segments)
    )
    rows = []
    for segment_name, label_value in segments:
        row = _report_row(input_image_path, segment_name, labelmap_index)
        values, warnings = _ruler_measurements(existing.get(segment_name) or [])
        row.update(values)
        if name_counts[segment_name] > 1:
            warnings.append(
                "Multiple segmentation labels are named %r; ruler matching is ambiguous."
                % segment_name
            )
        voxel_count = voxel_counts.get(label_value, 0)
        if not voxel_count:
            warnings.append("Segmentation label %r has no voxels." % segment_name)
        row["volume_mm3"] = format_float(voxel_count * voxel_volume_mm3)
        statistics, warning = (intensity_stats or {}).get(label_value, ({}, ""))
        row.update(statistics)
        if warning:
            warnings.append(warning)
        row["warnings"] = " ".join(warnings)
        rows.append(row)
    return rows


def orphan_rows(input_image_path, existing, named_segments, segment_name_counts=None):
    """Preserve ruler measurements whose names do not match a painted segment."""
    name_counts = (
        segment_name_counts
        if segment_name_counts is not None
        else Counter(named_segments)
    )
    rows = []
    for segment_name, rulers in sorted(existing.items()):
        if segment_name in named_segments:
            continue
        row = _report_row(input_image_path, segment_name)
        values, warnings = _ruler_measurements(rulers)
        row.update(values)
        if name_counts[segment_name] > 1:
            warnings.append(
                "Multiple segmentation labels are named %r; ruler matching is ambiguous."
                % segment_name
            )
        if segment_name:
            warnings.append("No segmentation label matches %r." % segment_name)
        else:
            warnings.append("Rulers have no assigned segment name.")
        row["warnings"] = " ".join(warnings)
        rows.append(row)
    return rows


def write_csv(rows, output_path):
    """Write fixed fields and ruler columns up to the largest group in this report."""
    import csv

    columns = dict.fromkeys(CSV_COLUMNS)
    for row in rows:
        columns.update(dict.fromkeys(row))
    ensure_parent_directory(output_path)
    with open(output_path, "w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
