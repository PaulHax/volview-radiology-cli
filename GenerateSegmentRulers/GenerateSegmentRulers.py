"""Generate diameter rulers for painted segments without rulers."""

import os
import sys

import itk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volview_cli_base.annotations import write_annotations  # noqa: E402
from volview_cli_base.assemble import assemble  # noqa: E402
from volview_cli_base.cli import run  # noqa: E402
from volview_cli_base.girder_input import resolve_girder_credentials  # noqa: E402
from volview_cli_base.segment_inputs import (  # noqa: E402
    read_input_annotations,
    read_labelmaps,
)
from volview_cli_base.segment_rulers import (  # noqa: E402
    MEASUREMENT_KINDS,
    build_output_annotations,
    generated_ruler,
    index_existing_rulers,
    measure_label,
    slice_axis_and_spacing,
)


def main(args):
    api_url, token = resolve_girder_credentials(args)
    labelmaps = read_labelmaps(args.inputLabelmap, api_url, token)

    annotations = read_input_annotations(
        getattr(args, "inputAnnotations", ""), api_url, token
    )
    all_segments = [
        segment for analysis in labelmaps for segment in analysis["segments"]
    ]
    existing = index_existing_rulers(annotations)

    rulers = []
    for analysis in labelmaps:
        missing = [
            (name, value)
            for name, value in analysis["segments"]
            if not existing.get(name)
        ]
        if not missing:
            continue
        labelmap = assemble([analysis["path"]])
        array = itk.array_view_from_image(labelmap)
        slice_axis, in_plane_spacing, in_plane_axes = slice_axis_and_spacing(
            labelmap
        )
        for segment_name, label_value in missing:
            measurement = measure_label(
                array, label_value, slice_axis, in_plane_spacing
            )
            if measurement is None:
                continue
            for kind in MEASUREMENT_KINDS:
                ruler = generated_ruler(
                    labelmap, slice_axis, in_plane_axes, measurement, kind, segment_name
                )
                if ruler is None:
                    continue
                rulers.append(ruler)
        del array, labelmap

    write_annotations(
        build_output_annotations(rulers, annotations), args.outputAnnotations
    )
    print(
        "Generated %d ruler(s) for %d segment(s) across %d label map(s)"
        % (len(rulers), len(all_segments), len(labelmaps)),
        flush=True,
    )


if __name__ == "__main__":
    run(main)
