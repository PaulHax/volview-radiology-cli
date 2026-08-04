"""Derive, audit, and report the in-plane diameters of a label map's regions.

An annotator paints one segment per region of interest and names it. The
measurements that belong beside it are two rulers: the region's longest
in-plane diameter (LD) and its widest extent perpendicular to that diameter
(SAD), both on the slice where the region is widest.

This module derives those rulers from the label map, joins them to the rulers
an annotator already placed, and reports both together. Three rules keep the
job idempotent and leave the annotator in charge:

- A region that already carries a ruler for a measurement keeps it. Nothing
  already placed is regenerated, moved, or replaced.
- A ruler whose label names no segment is never silently dropped; it is
  reported as a finding, because a misnamed ruler is the defect this job
  exists to catch.
- Geometry stays in the label map's own frame. Generated rulers ride the image
  axis nearest to superior-inferior, so an annotation's plane always aligns to
  an axis of the referenced image, which the client requires.

``LD`` and ``SAD`` are the label suffixes, not a claim about what the regions
are: the measurements are ordinary planar shape descriptors and the same
convention serves any label map whose segments are named.

``itk`` is imported lazily, inside the handful of functions that turn voxel
indices into world points, so the planar measurement and the report stay
usable -- and testable -- without loading ITK.
"""

import math

from volview_cli_base.annotations import SCHEMA_VERSION, SPACE
from volview_cli_base.paths import ensure_parent_directory
from volview_cli_base.roi_report import format_float, segment_names

LD = "LD"
SAD = "SAD"
MEASUREMENT_KINDS = (LD, SAD)

# The label an analyst reads and the report joins on: a segment name, a
# separator, and the measurement kind. Generation always writes a space; the
# audit also accepts the separators seen in hand-annotated sessions, so an
# existing ``n2-ld`` still joins to segment ``n2`` rather than being reported
# as an orphan.
_LABEL_SEPARATORS = " _-:"

# Styles for the labels this task creates. An input file that already defines a
# label of the same name wins, so a session's own colors survive a re-run.
GENERATED_LABEL_STYLES = {
    LD: {"color": "#ff5252", "strokeWidth": 2},
    SAD: {"color": "#40c4ff", "strokeWidth": 2},
}

SOURCE_EXISTING = "existing"
SOURCE_GENERATED = "generated"
SOURCE_MISSING = ""

# A superset of the volume-only report this task replaces: the same six region
# columns, then the measurement each region carries and what was found wrong.
CSV_COLUMNS = (
    "region_of_interest",
    "label_value",
    "voxel_count",
    "voxel_volume_mm3",
    "volume_mm3",
    "volume_ml",
    "ld_length_mm",
    "ld_source",
    "sad_length_mm",
    "sad_source",
    "slice",
    "warnings",
)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


def measurement_label(segment_name, kind):
    """The label a generated ruler carries: ``"n2 LD"``."""
    return "%s %s" % (segment_name, kind)


def parse_measurement_label(label_name):
    """Split ``"n2 LD"`` into ``("n2", "LD")``, or ``None`` if it is not one.

    Matching is case-insensitive on the kind and tolerant of the separator, so
    ``n2-ld`` and ``N2: sad`` both join. A name that merely ends in the letters
    (``"WELD"``) does not: a separator is required.
    """
    label = str(label_name or "").strip()
    upper = label.upper()
    for kind in (SAD, LD):
        if not upper.endswith(kind):
            continue
        prefix = label[: -len(kind)]
        if not prefix or prefix[-1] not in _LABEL_SEPARATORS:
            continue
        segment_name = prefix.rstrip(_LABEL_SEPARATORS)
        if segment_name:
            return segment_name, kind
    return None


def ruler_label(ruler):
    """The name to audit a ruler by.

    ``labelName`` is the shared label an annotator assigns and the analyst's
    report joins on; a per-tool ``name`` is the fallback for a ruler renamed
    individually.
    """
    return str(ruler.get("labelName") or ruler.get("name") or "")


def index_existing_rulers(annotations):
    """Group an annotations file's rulers by the measurement they claim.

    Returns ``({(segment_name, kind): [ruler, ...]}, [unparsed_label, ...])``.
    Every ruler lands in exactly one of the two, so nothing is dropped.
    """
    tools = (annotations or {}).get("tools") or {}
    by_measurement = {}
    unparsed = []
    for ruler in tools.get("rulers") or []:
        parsed = parse_measurement_label(ruler_label(ruler))
        if parsed is None:
            unparsed.append(ruler_label(ruler))
            continue
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
    unit direction in LPS, so row 2 holds each axis' superior component. The
    axial slices of an obliquely acquired volume are the ones stacked along
    this axis, which keeps a generated annotation's plane aligned to an image
    axis even when the volume is not perfectly axial.
    """
    return max(range(3), key=lambda axis: abs(float(direction[2][axis])))


def _hull_candidates(rows, columns):
    """The per-row extreme points, a superset of the convex hull's vertices.

    A point lying strictly between two others in its own row is inside their
    segment, so it can never be an extreme point in any direction. Keeping only
    each row's first and last column therefore preserves every hull vertex --
    and so the longest chord's endpoints -- while bounding the pairwise search
    to two points per row.
    """
    import numpy as np

    order = np.lexsort((columns, rows))
    ordered_rows = rows[order]
    starts = np.empty(ordered_rows.shape, dtype=bool)
    ends = np.empty(ordered_rows.shape, dtype=bool)
    starts[0] = ends[-1] = True
    changed = ordered_rows[1:] != ordered_rows[:-1]
    starts[1:] = changed
    ends[:-1] = changed
    keep = order[starts | ends]
    return rows[keep], columns[keep]


def _longest_chord(points_mm):
    """The farthest-apart pair in ``points_mm``: ``(length, index, index)``."""
    import numpy as np

    deltas = points_mm[:, None, :] - points_mm[None, :, :]
    distances = np.sqrt((deltas**2).sum(axis=-1))
    first, second = np.unravel_index(int(np.argmax(distances)), distances.shape)
    return float(distances[first, second]), int(first), int(second)


def _perpendicular_extent(points_mm, start_mm, end_mm, step_mm):
    """The widest extent perpendicular to ``start_mm``->``end_mm``.

    The region is swept in bins along the long axis and the widest bin wins, so
    the reported short axis is the region's widest span across its longest
    diameter rather than a chord through the centroid. Returns
    ``(length, index, index)`` into ``points_mm``; the endpoints are real
    foreground points, though on a concave region the segment between them can
    leave the mask.
    """
    import numpy as np

    direction = end_mm - start_mm
    length = float(np.linalg.norm(direction))
    if length == 0:
        return 0.0, None, None

    along_axis = direction / length
    across_axis = np.array([-along_axis[1], along_axis[0]])
    relative = points_mm - start_mm
    along = relative @ along_axis
    across = relative @ across_axis

    bin_count = max(1, int(math.ceil(length / step_mm)))
    edges = np.linspace(0.0, length, bin_count + 1)
    bins = np.clip(np.searchsorted(edges, along, side="right") - 1, 0, bin_count - 1)

    widest = 0.0
    endpoints = (None, None)
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
    return widest, endpoints[0], endpoints[1]


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
    ld_mm, first, second = _longest_chord(hull_mm)

    points_mm = np.column_stack([rows * row_spacing, columns * column_spacing])
    step_mm = min(row_spacing, column_spacing) * 0.5
    sad_mm, low, high = _perpendicular_extent(
        points_mm, hull_mm[first], hull_mm[second], step_mm
    )

    measurement = {
        "ld_mm": ld_mm,
        "sad_mm": sad_mm,
        "ld_points": (
            (int(hull_rows[first]), int(hull_columns[first])),
            (int(hull_rows[second]), int(hull_columns[second])),
        ),
        "sad_points": None,
    }
    if low is not None and high is not None:
        measurement["sad_points"] = (
            (int(rows[low]), int(columns[low])),
            (int(rows[high]), int(columns[high])),
        )
    return measurement


def measure_label(array, value, slice_axis, in_plane_spacing_mm):
    """Measure one label value across every slice, keeping the widest.

    ``array`` is the label map in storage order, ``slice_axis`` the array axis
    the slices stack along, and ``in_plane_spacing_mm`` the spacing of the two
    remaining array axes in their natural order. Returns ``None`` when the
    label is absent or too small to span a chord; otherwise the winning slice's
    measurement plus its ``slice`` index.
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


def frame_of_reference(labelmap, slice_axis, slice_index):
    """The plane a generated ruler sits in, aligned to an image axis.

    ``planeNormal`` is the slice axis' own direction, so the client can always
    match the plane to an image axis rather than rejecting it as oblique;
    ``planeOrigin`` is a point on that slice.
    """
    import itk

    direction = itk.array_from_matrix(labelmap.GetDirection())
    image_axis = 2 - slice_axis
    origin_index = [0, 0, 0]
    origin_index[slice_axis] = slice_index
    return {
        "planeNormal": [float(direction[row][image_axis]) for row in range(3)],
        "planeOrigin": world_point(labelmap, origin_index),
    }


def generated_ruler(labelmap, slice_axis, in_plane_axes, measurement, kind, label):
    """One ruler for ``kind``, or ``None`` when that measurement has no points."""
    points = measurement[kind.lower() + "_points"]
    if not points:
        return None

    world = []
    for in_plane in points:
        array_index = [0, 0, 0]
        array_index[slice_axis] = measurement["slice"]
        for axis, position in zip(in_plane_axes, in_plane):
            array_index[axis] = position
        world.append(world_point(labelmap, array_index))

    return {
        "firstPoint": world[0],
        "secondPoint": world[1],
        "frameOfReference": frame_of_reference(
            labelmap, slice_axis, measurement["slice"]
        ),
        "labelName": label,
        "name": label,
        "slice": measurement["slice"],
    }


def build_output_annotations(rulers, styles_by_label, input_annotations):
    """The additive result: only the rulers this run generated.

    Input tools are not echoed because annotation results are additive. A label
    the input file already defines keeps its own style, so a re-run never
    restyles an annotator's labels.
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


def _joined(values):
    return ";".join(str(value) for value in values if value != "")


def labelmap_segments(metadata, present_values):
    """``[(segment name, label value)]`` for the label map's painted segments.

    Embedded ``.seg.nrrd`` segment names are the region IDs the report joins
    on. A value the metadata does not name still gets an entry under a
    deterministic name, matching the region report's fallback, so an unnamed
    segment is visible rather than absent. A list rather than a mapping: two
    segments may answer to one name, and collapsing them would hide exactly the
    defect this job reports.
    """
    names = segment_names(metadata)
    return [
        (names.get(value, "Region %d" % value), value)
        for value in sorted(present_values)
    ]


def segment_rows(segments, measurements, existing, voxel_counts, voxel_volume_mm3):
    """One report row per painted segment, joined to the rulers it already has.

    ``segments`` is what ``labelmap_segments`` returns; ``measurements`` and
    ``voxel_counts`` are keyed by label value and may be missing an entry. A
    segment whose label map has no voxels still gets a row, because a silently
    absent region is the report's most important finding.
    """
    duplicated = {
        name
        for index, (name, _) in enumerate(segments)
        if any(earlier == name for earlier, _ in segments[:index])
    }

    rows = []
    for segment_name, label_value in segments:
        measurement = measurements.get(label_value)
        voxel_count = voxel_counts.get(label_value, 0)
        volume_mm3 = voxel_count * voxel_volume_mm3
        warnings = []
        if segment_name in duplicated:
            # Two segments answering to one name make every ruler naming it
            # ambiguous, so the join below is reported rather than trusted.
            warnings.append(
                "Multiple segmentation labels are named %r; ruler matching is ambiguous."
                % segment_name
            )
        if not voxel_count:
            warnings.append("Segmentation label %r has no voxels." % segment_name)

        row = {
            "region_of_interest": segment_name,
            "label_value": str(label_value),
            "voxel_count": str(voxel_count),
            "voxel_volume_mm3": format_float(voxel_volume_mm3),
            "volume_mm3": format_float(volume_mm3),
            "volume_ml": format_float(volume_mm3 / 1000.0),
            "slice": "" if measurement is None else str(measurement["slice"]),
        }
        for kind in MEASUREMENT_KINDS:
            column = kind.lower()
            rulers = existing.get((segment_name, kind)) or []
            if len(rulers) > 1:
                warnings.append(
                    "Found %d %s rulers for segmentation label %r; expected at most one."
                    % (len(rulers), kind, segment_name)
                )
            if rulers:
                row[column + "_length_mm"] = _joined(
                    format_float(ruler_length_mm(ruler) or 0.0) for ruler in rulers
                )
                row[column + "_source"] = SOURCE_EXISTING
            elif measurement is not None:
                row[column + "_length_mm"] = format_float(measurement[column + "_mm"])
                row[column + "_source"] = SOURCE_GENERATED
            else:
                row[column + "_length_mm"] = ""
                row[column + "_source"] = SOURCE_MISSING
                warnings.append(
                    "No %s ruler exists and one could not be generated for "
                    "segmentation label %r." % (kind, segment_name)
                )

        row["warnings"] = " ".join(warnings)
        rows.append(row)
    return rows


def orphan_rows(existing, unparsed_labels, named_segments):
    """One row per ruler that no painted segment claims.

    These are the annotation defects the job checks for: a ruler whose label
    names no segment (a typo, or a region never painted) and a ruler whose
    label is not a measurement at all.
    """
    rows = []
    for (segment_name, kind), rulers in sorted(existing.items()):
        if segment_name in named_segments:
            continue
        row = dict.fromkeys(CSV_COLUMNS, "")
        row["region_of_interest"] = segment_name
        row[kind.lower() + "_length_mm"] = _joined(
            format_float(ruler_length_mm(ruler) or 0.0) for ruler in rulers
        )
        row[kind.lower() + "_source"] = SOURCE_EXISTING
        labels = sorted({ruler_label(ruler) for ruler in rulers})
        if len(labels) == 1:
            row["warnings"] = (
                "Ruler label %r does not match any segmentation label." % labels[0]
            )
        else:
            row["warnings"] = (
                "Ruler labels %s do not match any segmentation label."
                % ", ".join(repr(label) for label in labels)
            )
        rows.append(row)

    for label in sorted(set(unparsed_labels)):
        row = dict.fromkeys(CSV_COLUMNS, "")
        row["region_of_interest"] = label
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
