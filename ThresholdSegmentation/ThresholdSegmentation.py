"""ITK threshold segmentation CLI.

Input assembly + the v1 b3 Girder fetch live in the shared ``volview_cli_base``
package. Uses real ITK (the ``itk`` package), per D10. The output is a
compressed ``.seg.nrrd`` labelmap (uint8, background 0) whose single segment's
name/color travel inside the file as Slicer-convention metadata (Chunk 34).
"""

import os
import sys

import itk
from slicer_cli_web import CLIArgumentParser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volview_cli_base.assemble import (  # noqa: E402
    assemble,
    to_scalar_float,
)
from volview_cli_base.girder_input import (  # noqa: E402
    resolve_girder_credentials,
    resolve_inputs_to_local_paths,
)
from volview_cli_base.segnrrd import write_segmentation  # noqa: E402


def _format_threshold(value):
    return ("%g" % float(value)).rstrip(".")


def _segment_name(lower, upper):
    return "Threshold %s-%s" % (
        _format_threshold(lower),
        _format_threshold(upper),
    )


def main(args):
    labelmap_path = args.outputLabelmap
    lower = float(args.lowerThreshold)
    upper = float(args.upperThreshold)

    if lower > upper:
        raise ValueError("Lower threshold must be <= upper threshold")

    api_url, token = resolve_girder_credentials(args)
    local_paths = resolve_inputs_to_local_paths(
        args.inputVolume, api_url=api_url, token=token
    )
    print(f"Assembling volume from {len(local_paths)} file(s)", flush=True)
    image = to_scalar_float(assemble(local_paths))

    print(f"Thresholding intensities in [{lower}, {upper}]", flush=True)
    mask = itk.binary_threshold_image_filter(
        image,
        lower_threshold=lower,
        upper_threshold=upper,
        inside_value=1,
        outside_value=0,
    )
    labelmap = mask.astype(itk.UC)

    descriptors = [{
        "value": 1,
        "name": _segment_name(lower, upper),
        "color": [255, 0, 0, 255],
    }]
    print(f"Writing labelmap to {labelmap_path}", flush=True)
    write_segmentation(labelmap, labelmap_path, descriptors)

    stats = itk.StatisticsImageFilter.New(labelmap)
    stats.Update()
    voxel_count = int(stats.GetSum())

    print(f"Done. {voxel_count} voxels labelled.", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--xml":
        xml_spec = os.path.splitext(sys.argv[0])[0] + ".xml"
        with open(xml_spec) as f:
            print(f.read())
        sys.exit(0)
    main(CLIArgumentParser().parse_args())
