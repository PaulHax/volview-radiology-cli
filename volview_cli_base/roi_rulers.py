"""Derive, audit, and report the in-plane diameters of a label map's regions.

Each painted segment gets two rulers: the region's longest in-plane diameter
(LD) and its widest extent perpendicular to that diameter (SAD), both on the
slice where the region is widest. This module derives the rulers a region is
missing, joins them to the ones an annotator already placed, and reports both.
``LD`` and ``SAD`` are label suffixes, not a claim about what the regions are.

``itk`` is imported lazily so the planar measurement and the report stay
testable without it.
"""

import math
from collections import Counter

from volview_cli_base.annotations import SCHEMA_VERSION, SPACE
from volview_cli_base.paths import ensure_parent_directory
from volview_cli_base.roi_report import format_float, segment_names

LD = "LD"
SAD = "SAD"
MEASUREMENT_KINDS = (LD, SAD)

# A label is a segment name, a separator, and the measurement kind. Generation
# always writes a space; the audit also accepts the separators and casing seen
# in hand-annotated sessions.
_LABEL_SEPARATORS = " _-:"

# Styles for the labels this task creates. An input file that already defines a
# label of the same name wins, so a session's own colors survive a re-run.
GENERATED_LABEL_STYLES = {
    LD: {"color": "#ff5252", "strokeWidth": 2},
    SAD: {"color": "#40c4ff", "strokeWidth": 2},
}

CSV_COLUMNS = (
    "input_image_path",
    "roi_name",
    "labelmap_index",
    "ld_length_mm",
    "sad_length_mm",
    "volume_mm3",
    "warnings",
)


# ---------------------------------------------------------------------------
# Labelmap inputs
# ---------------------------------------------------------------------------


def reject_multi_file_dicom_series(paths):
    """Raise when two or more of ``paths`` belong to the same DICOM series.

    Each labelmap file is measured as its own complete label map (see the
    README's "Region of Interest Rulers" limitations): a multi-file DICOM
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


def measurement_label(segment_name, kind):
    """The label a generated ruler carries: ``"n2 LD"``."""
    return "%s %s" % (segment_name, kind)


def parse_measurement_label(label_name):
    """Split ``"n2 LD"`` into ``("n2", "LD")``, or ``None`` if it is not one.

    A separator is required, so ``"WELD"`` does not parse.
    """
    label = str(label_name or "").strip()
    for kind in MEASUREMENT_KINDS:
        if not label.upper().endswith(kind):
            continue
        prefix = label[: -len(kind)]
        name = prefix.rstrip(_LABEL_SEPARATORS)
        if name and name != prefix:  # a separator is required
            return name, kind
    return None


def ruler_label(ruler):
    """The name to audit by: the shared ``labelName``, else the per-tool ``name``."""
    return str(ruler.get("labelName") or ruler.get("name") or "")


def index_existing_rulers(annotations):
    """Group an annotations file's rulers by the measurement they claim.

    Returns ``({(segment_name, kind): [ruler, ...]}, [unparsed_label, ...])``;
    every ruler lands in exactly one of the two, so nothing is dropped.
    """
    by_measurement = {}
    unparsed = []
    for ruler in ((annotations or {}).get("tools") or {}).get("rulers") or []:
        label = ruler_label(ruler)
        parsed = parse_measurement_label(label)
        if parsed is None:
            unparsed.append(label)
        else:
            by_measurement.setdefault(parsed, []).append(ruler)
    return by_measurement, unparsed


def ruler_length_mm(ruler):
    """A ruler's world length in millimetres, or ``None`` without two points."""
    first = ruler.get("firstPoint") or []
    second = ruler.get("secondPoint") or []
    if len(first) != 3 or len(second) != 3:
        return None
    return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(first, second)))


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

    The region is swept in bins along the long axis and the widest bin wins, so
    the reported short axis is the region's widest span across its longest
    diameter rather than a chord through the centroid. The endpoints are real
    foreground points, though on a concave region the segment between them can
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


def build_output_annotations(rulers, styles_by_label, input_annotations):
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
            label: dict(defined.get(label, style))
            for label, style in styles_by_label.items()
        }
    }
    return result


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _lengths_mm(rulers):
    """The CSV cell for one or more rulers' world lengths."""
    return ";".join(format_float(ruler_length_mm(ruler) or 0.0) for ruler in rulers)


def _report_row(input_image_path, roi_name, labelmap_index=None):
    """A blank report row, ready for whichever cells the caller fills in."""
    row = dict.fromkeys(CSV_COLUMNS, "")
    row["input_image_path"] = input_image_path
    row["roi_name"] = roi_name
    if labelmap_index is not None:
        row["labelmap_index"] = labelmap_index
    return row


def labelmap_segments(metadata, present_values):
    """``[(segment name, label value)]`` for the label map's painted segments.

    Embedded ``.seg.nrrd`` segment names are the region IDs the report joins
    on; an unnamed value falls back to a deterministic name. A list rather than
    a mapping, because two segments may answer to one name and collapsing them
    would hide exactly the defect this job reports.
    """
    names = segment_names(metadata)
    return [
        (names.get(value, "Region %d" % value), value)
        for value in sorted(present_values)
    ]


def segment_rows(
    input_image_path,
    segments,
    measurements,
    existing,
    voxel_counts,
    voxel_volume_mm3,
    segment_name_counts=None,
    labelmap_index=None,
):
    """One report row per painted segment, joined to the rulers it already has.

    ``segments`` is what ``labelmap_segments`` returns; ``measurements`` and
    ``voxel_counts`` are keyed by label value and may be missing an entry. A
    segment whose label map has no voxels still gets a row, because a silently
    absent region is the report's most important finding. ``labelmap_index``
    identifies which input labelmap the rows came from, so two segments named
    alike in different label maps still resolve to distinct rows.
    """
    name_counts = (
        segment_name_counts
        if segment_name_counts is not None
        else Counter(name for name, _ in segments)
    )

    rows = []
    for segment_name, label_value in segments:
        measurement = measurements.get(label_value)
        voxel_count = voxel_counts.get(label_value, 0)
        warnings = []
        if name_counts[segment_name] > 1:
            # Two segments answering to one name make every ruler naming it
            # ambiguous, so the join below is reported rather than trusted.
            warnings.append(
                "Multiple segmentation labels are named %r; ruler matching is ambiguous."
                % segment_name
            )
        if not voxel_count:
            warnings.append("Segmentation label %r has no voxels." % segment_name)

        row = _report_row(input_image_path, segment_name, labelmap_index)
        row["volume_mm3"] = format_float(voxel_count * voxel_volume_mm3)
        for kind in MEASUREMENT_KINDS:
            column = kind.lower()
            rulers = existing.get((segment_name, kind)) or []
            if len(rulers) > 1:
                warnings.append(
                    "Found %d %s rulers for segmentation label %r; expected at most one."
                    % (len(rulers), kind, segment_name)
                )
            if rulers:
                row[column + "_length_mm"] = _lengths_mm(rulers)
            elif measurement is not None:
                row[column + "_length_mm"] = format_float(measurement[column + "_mm"])
            else:
                warnings.append(
                    "No %s ruler exists and one could not be generated for "
                    "segmentation label %r." % (kind, segment_name)
                )

        row["warnings"] = " ".join(warnings)
        rows.append(row)
    return rows


def orphan_rows(input_image_path, existing, unparsed_labels, named_segments):
    """One row per ruler that no painted segment claims.

    Either a ruler whose label names no segment -- a typo, or a region never
    painted -- or a ruler whose label is not a measurement at all.
    """
    rows = []
    for (segment_name, kind), rulers in sorted(existing.items()):
        if segment_name in named_segments:
            continue
        labels = sorted({ruler_label(ruler) for ruler in rulers})
        row = _report_row(input_image_path, segment_name)
        row[kind.lower() + "_length_mm"] = _lengths_mm(rulers)
        row["warnings"] = "No segmentation label matches %s." % ", ".join(
            map(repr, labels)
        )
        rows.append(row)

    for label in sorted(set(unparsed_labels)):
        row = _report_row(input_image_path, label)
        row["warnings"] = (
            "Ruler label %r is not a recognized measurement label; expected "
            "'<segmentation label> LD' or '<segmentation label> SAD'." % label
        )
        rows.append(row)
    return rows


def write_csv(rows, output_path):
    """Write report rows to ``output_path``, header included when empty."""
    import csv

    ensure_parent_directory(output_path)
    with open(output_path, "w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
