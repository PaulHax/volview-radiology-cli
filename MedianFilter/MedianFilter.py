"""ITK median filter -- slicer_cli_web-compatible CLI.

The shared ``volview_cli_base`` package resolves inputs and assembles multi-file
DICOM series before this module applies the filter.
"""

import os
import sys

import itk
from slicer_cli_web import CLIArgumentParser

# The shared base package lives at the repo root (one level above this CLI's
# own directory); make it importable when slicer_cli_web runs the script by
# absolute path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volview_cli_base.assemble import assemble, write_image  # noqa: E402
from volview_cli_base.girder_input import (  # noqa: E402
    resolve_girder_credentials,
    resolve_inputs_to_local_paths,
)


def main(args):
    radius = int(args.radius)
    api_url, token = resolve_girder_credentials(args)

    local_paths = resolve_inputs_to_local_paths(
        args.inputVolume, api_url=api_url, token=token
    )
    print(f"Assembling volume from {len(local_paths)} file(s)", flush=True)
    image = assemble(local_paths)

    region_size = image.GetLargestPossibleRegion().GetSize()
    dims = [region_size[i] for i in range(image.GetImageDimension())]
    print(f"Applying median filter (radius={radius}) to image of size {dims}",
          flush=True)
    filtered = itk.median_image_filter(image, radius=radius)

    print(f"Writing {args.outputVolume}", flush=True)
    write_image(filtered, args.outputVolume)
    print("Done.", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--xml":
        xml_spec = os.path.splitext(sys.argv[0])[0] + ".xml"
        with open(xml_spec) as f:
            print(f.read())
        sys.exit(0)
    main(CLIArgumentParser().parse_args())
