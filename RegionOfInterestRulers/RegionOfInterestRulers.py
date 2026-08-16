"""Finish and check a label map's ruler annotations, and report both.

Reads the painted segments, generates the diameter rulers that are missing,
leaves the ones an annotator already placed untouched, and writes a CSV naming
every region alongside its measurements and any defect found.
"""

import os
import sys
from collections import Counter

import itk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volview_cli_base.annotations import (  # noqa: E402
    SCHEMA_VERSION,
    SPACE,
    read_annotations,
    write_annotations,
)
from volview_cli_base.assemble import assemble  # noqa: E402
from volview_cli_base.cli import run  # noqa: E402
from volview_cli_base.girder_input import (  # noqa: E402
    resolve_girder_credentials,
    resolve_girder_item_path,
    resolve_inputs_to_local_paths,
)
from volview_cli_base.roi_report import image_metadata, voxel_summary  # noqa: E402
from volview_cli_base.roi_rulers import (  # noqa: E402
    GENERATED_LABEL_STYLES,
    MEASUREMENT_KINDS,
    build_output_annotations,
    generated_ruler,
    index_existing_rulers,
    labelmap_segments,
    measure_label,
    measurement_label,
    orphan_rows,
    reject_multi_file_dicom_series,
    segment_rows,
    slice_axis_and_spacing,
    write_csv,
)


def read_input_annotations(value, api_url, token):
    """The annotations file, or an empty one when the parameter is unbound.

    An absent argument means "nothing placed yet", the task's starting case,
    not an error: VolView binds an annotations input only once the image has a
    finished annotation.
    """
    if not str(value or "").strip():
        return {"schemaVersion": SCHEMA_VERSION, "space": SPACE, "tools": {}}
    local_paths = resolve_inputs_to_local_paths(value, api_url=api_url, token=token)
    if len(local_paths) != 1:
        raise ValueError("expected one annotations file, received %d" % len(local_paths))
    return read_annotations(local_paths[0])


def main(args):
    api_url, token = resolve_girder_credentials(args)
    input_image_path = resolve_girder_item_path(
        args.inputVolume, api_url=api_url, token=token
    )
    labelmap_paths = resolve_inputs_to_local_paths(
        args.inputLabelmap, api_url=api_url, token=token
    )
    reject_multi_file_dicom_series(labelmap_paths)
    print("Reading %d label map(s)" % len(labelmap_paths), flush=True)

    annotations = read_input_annotations(
        getattr(args, "inputAnnotations", ""), api_url, token
    )
    existing, unparsed = index_existing_rulers(annotations)

    labelmaps = []
    rulers = []
    styles = {}
    for path in labelmap_paths:
        labelmap = assemble([path])
        if int(labelmap.GetNumberOfComponentsPerPixel()) != 1:
            raise ValueError("input label map must have exactly one component per pixel")
        array = itk.array_view_from_image(labelmap)
        voxel_counts, voxel_volume_mm3 = voxel_summary(
            array, labelmap.GetSpacing()
        )
        slice_axis, in_plane_spacing, in_plane_axes = slice_axis_and_spacing(
            labelmap
        )
        segments = labelmap_segments(image_metadata(labelmap), list(voxel_counts))

        measurements = {}
        for segment_name, label_value in segments:
            measurement = measure_label(
                array, label_value, slice_axis, in_plane_spacing
            )
            if measurement is None:
                continue
            measurements[label_value] = measurement
            for kind in MEASUREMENT_KINDS:
                if existing.get((segment_name, kind)):
                    continue  # the annotator already placed this one
                label = measurement_label(segment_name, kind)
                ruler = generated_ruler(
                    labelmap, slice_axis, in_plane_axes, measurement, kind, label
                )
                if ruler is None:
                    continue
                rulers.append(ruler)
                styles[label] = GENERATED_LABEL_STYLES[kind]

        labelmaps.append(
            {
                "segments": segments,
                "measurements": measurements,
                "voxel_counts": voxel_counts,
                "voxel_volume_mm3": voxel_volume_mm3,
            }
        )

    write_annotations(
        build_output_annotations(rulers, styles, annotations), args.outputAnnotations
    )

    all_segments = [
        segment for analysis in labelmaps for segment in analysis["segments"]
    ]
    name_counts = Counter(name for name, _ in all_segments)
    rows = []
    for index, analysis in enumerate(labelmaps, start=1):
        rows.extend(
            segment_rows(
                input_image_path,
                analysis["segments"],
                analysis["measurements"],
                existing,
                analysis["voxel_counts"],
                analysis["voxel_volume_mm3"],
                segment_name_counts=name_counts,
                labelmap_index=index,
            )
        )
    rows.extend(
        orphan_rows(
            input_image_path, existing, unparsed, {name for name, _ in all_segments}
        )
    )
    write_csv(rows, args.outputReport)

    print(
        "Generated %d ruler(s) for %d region(s) across %d label map(s); "
        "wrote %d report row(s) to %s"
        % (
            len(rulers),
            len(all_segments),
            len(labelmaps),
            len(rows),
            args.outputReport,
        ),
        flush=True,
    )


if __name__ == "__main__":
    run(main)
