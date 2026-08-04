"""Read and write VolView ``*.annotations.json`` files.

Coordinates are world LPS millimetres. Validation mirrors VolView's normative
contract and excludes session-only fields.
"""

import json
import math

from volview_cli_base.paths import ensure_parent_directory

SCHEMA_VERSION = 1
SPACE = "LPS"
TOOL_KINDS = ("rulers", "rectangles", "polygons")
MAX_SAFE_INTEGER = 2**53 - 1
_RESERVED_RECORD_KEYS = {"__proto__"}
_FRAME_FIELDS = {"planeNormal", "planeOrigin"}
_LABEL_FIELDS = {"color", "strokeWidth", "fillColor"}

# Fields every tool kind may carry. ``slice``/``frame`` are advisory echoes of
# where the producer saw the annotation; the client re-derives placement from
# ``frameOfReference``.
_CORE_FIELDS = ("frameOfReference", "slice", "frame", "labelName", "name", "metadata")
# The geometry each tool kind carries: the field name mapped to how many points
# it holds. ``1`` is a bare ``[x, y, z]``; a larger count is an array of points
# with that many at minimum (a polygon needs three to bound an area).
_GEOMETRY_FIELDS = {
    "rulers": {"firstPoint": 1, "secondPoint": 1},
    "rectangles": {"firstPoint": 1, "secondPoint": 1},
    "polygons": {"points": 3},
}


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_point(value, where):
    numbers = (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(_is_number(v) and math.isfinite(v) for v in value)
    )
    if not numbers:
        raise ValueError(
            "%s must be three finite numbers in world LPS millimeters" % where
        )


def _validate_core_fields(tool, where):
    """The advisory core fields, mirroring the client's zod constraints.

    ``labelName`` is validated with the label namespaces.
    """
    if "slice" in tool:
        value = tool["slice"]
        if not (_is_number(value) and math.isfinite(value)):
            raise ValueError("%s.slice must be a finite number" % where)
    if "frame" in tool:
        value = tool["frame"]
        # A frame indexes a cine loop: only a non-negative integer is
        # honorable. A whole-valued float (JSON has one number type) counts.
        integral = (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and value.is_integer()
        )
        if not (integral and 0 <= value <= MAX_SAFE_INTEGER):
            raise ValueError("%s.frame must be a non-negative integer" % where)
    if "name" in tool and not isinstance(tool["name"], str):
        raise ValueError("%s.name must be a string" % where)
    if "metadata" in tool:
        metadata = tool["metadata"]
        strings = isinstance(metadata, dict) and all(
            isinstance(key, str)
            and key not in _RESERVED_RECORD_KEYS
            and isinstance(value, str)
            for key, value in metadata.items()
        )
        if not strings:
            raise ValueError("%s.metadata must be an object of string values" % where)


def _validate_tool(kind, index, tool, labels):
    where = "tools.%s[%d]" % (kind, index)
    if not isinstance(tool, dict):
        raise ValueError("%s must be an object" % where)

    unknown = sorted(set(tool) - set(_CORE_FIELDS) - set(_GEOMETRY_FIELDS[kind]))
    if unknown:
        raise ValueError(
            "%s carries fields that may not ride on the wire: %s"
            % (where, ", ".join(unknown))
        )

    frame = tool.get("frameOfReference")
    if not isinstance(frame, dict):
        raise ValueError("%s is missing its frameOfReference" % where)
    unknown_frame_fields = sorted(set(frame) - _FRAME_FIELDS)
    if unknown_frame_fields:
        raise ValueError(
            "%s.frameOfReference carries unknown fields: %s"
            % (where, ", ".join(unknown_frame_fields))
        )
    plane_normal = frame.get("planeNormal")
    _validate_point(plane_normal, where + ".frameOfReference.planeNormal")
    if math.hypot(*plane_normal) == 0:
        raise ValueError(
            "%s.frameOfReference.planeNormal must be a nonzero vector" % where
        )
    _validate_point(frame.get("planeOrigin"), where + ".frameOfReference.planeOrigin")
    _validate_core_fields(tool, where)

    for field, minimum_points in _GEOMETRY_FIELDS[kind].items():
        if minimum_points == 1:
            _validate_point(tool.get(field), "%s.%s" % (where, field))
            continue
        points = tool.get(field)
        if not isinstance(points, list) or len(points) < minimum_points:
            raise ValueError("%s must have at least three points" % where)
        for position, point in enumerate(points):
            _validate_point(point, "%s.%s[%d]" % (where, field, position))

    if "labelName" not in tool or tool["labelName"] == "":
        return
    label_name = tool["labelName"]
    if not isinstance(label_name, str):
        raise ValueError("%s.labelName must be a string" % where)
    if label_name not in labels.get(kind, {}):
        raise ValueError(
            "%s references label %r, which labels.%s does not declare"
            % (where, label_name, kind)
        )


def load_annotations(data):
    """Validate a parsed annotations file, returning it unchanged.

    Raises ``ValueError`` with the offending path for anything the contract
    refuses.
    """
    if not isinstance(data, dict):
        raise ValueError("annotations file must be a JSON object")
    if data.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError(
            "unsupported schemaVersion %r; this CLI speaks version %d"
            % (data.get("schemaVersion"), SCHEMA_VERSION)
        )
    if data.get("space") != SPACE:
        raise ValueError(
            "unsupported space %r; coordinates must be world %s millimeters"
            % (data.get("space"), SPACE)
        )

    labels = data.get("labels", {})
    if not isinstance(labels, dict):
        raise ValueError("labels must be an object keyed by tool kind")
    for kind, namespace in labels.items():
        if kind not in TOOL_KINDS:
            raise ValueError("labels.%s is not a tool kind" % kind)
        if not isinstance(namespace, dict):
            raise ValueError("labels.%s must be an object keyed by label name" % kind)
        for label_name, definition in namespace.items():
            if not isinstance(label_name, str) or label_name in _RESERVED_RECORD_KEYS:
                raise ValueError("labels.%s contains a reserved label name" % kind)
            if not isinstance(definition, dict):
                raise ValueError("labels.%s.%s must be an object" % (kind, label_name))
            unknown = sorted(set(definition) - _LABEL_FIELDS)
            if unknown:
                raise ValueError(
                    "labels.%s.%s carries unknown fields: %s"
                    % (kind, label_name, ", ".join(unknown))
                )
            for field in ("color", "fillColor"):
                if field in definition and not isinstance(definition[field], str):
                    raise ValueError(
                        "labels.%s.%s.%s must be a string" % (kind, label_name, field)
                    )
            if "strokeWidth" in definition:
                stroke_width = definition["strokeWidth"]
                if not (_is_number(stroke_width) and math.isfinite(stroke_width)):
                    raise ValueError(
                        "labels.%s.%s.strokeWidth must be a finite number"
                        % (kind, label_name)
                    )

    tools = data.get("tools")
    if not isinstance(tools, dict):
        raise ValueError("annotations file must carry a tools object")
    for kind, entries in tools.items():
        if kind not in TOOL_KINDS:
            raise ValueError("tools.%s is not a tool kind" % kind)
        if not isinstance(entries, list):
            raise ValueError("tools.%s must be an array" % kind)
        for index, tool in enumerate(entries):
            _validate_tool(kind, index, tool, labels)

    return data


def read_annotations(path):
    """Parse and validate an annotations file from disk."""
    with open(path, encoding="utf-8") as stream:
        return load_annotations(json.load(stream))


def write_annotations(annotations, output_path):
    """Validate, then write an annotations file (creating parent directories).

    Serialized before the file opens: ``allow_nan=False`` is a final guard
    against the NaN and Infinity literals JavaScript's ``JSON.parse`` rejects,
    and failing during ``dump`` would otherwise leave a partial file behind.
    """
    load_annotations(annotations)
    payload = json.dumps(annotations, indent=2, sort_keys=True, allow_nan=False)
    ensure_parent_directory(output_path)
    with open(output_path, "w", encoding="utf-8") as stream:
        stream.write(payload + "\n")
