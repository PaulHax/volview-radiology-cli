"""Masked median filter -- background ``<image>`` + ``<image type="label">`` mask.

Chunk 16's labelmap-consuming CLI. It fetches TWO inputs -- a scalar background
volume and a painted labelmap -- runs an ITK median filter over the background,
and composites the filtered result back only where the labelmap is nonzero;
voxels outside the mask keep their original values. The output is a plain image,
so the facade maps it to the ``add-base-image`` result intent and it loads back
into VolView as a new base image.

Input assembly (multi-slice DICOM -> one correctly spaced volume) and the v1 b3
Girder fetch both live in the shared ``volview_cli_base`` package; the masked
composite is the pure-numpy ``volview_cli_base.masked`` primitive. The
background is cast to scalar float (the filter domain); the labelmap keeps its
native integer label values (never ``to_scalar_float``'d) so a nonzero-label
mask is exact. Uses real ITK (the ``itk`` package), per D10.
"""

import os
import sys

import itk
from slicer_cli_web import CLIArgumentParser

# The shared base package lives at the repo root (one level above this CLI's
# own directory); make it importable when slicer_cli_web runs the script by
# absolute path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volview_cli_base.assemble import (  # noqa: E402
    assemble,
    to_scalar_float,
    write_image,
)
from volview_cli_base.girder_input import (  # noqa: E402
    resolve_girder_credentials,
    resolve_inputs_to_local_paths,
)
from volview_cli_base.masked import (  # noqa: E402
    composite_inside_mask,
    nonzero_mask,
)


def main(args):
    radius = int(args.radius)
    api_url, token = resolve_girder_credentials(args)

    background_paths = resolve_inputs_to_local_paths(
        args.inputVolume, api_url=api_url, token=token
    )
    labelmap_paths = resolve_inputs_to_local_paths(
        args.inputLabelmap, api_url=api_url, token=token
    )
    print(
        "Assembling background from %d file(s) and labelmap from %d file(s)"
        % (len(background_paths), len(labelmap_paths)),
        flush=True,
    )
    # Background: scalar float (the filter domain). Labelmap: native integer
    # labels preserved -- do NOT to_scalar_float it, so nonzero labels are exact.
    image = to_scalar_float(assemble(background_paths))
    labelmap = assemble(labelmap_paths)

    print("Applying median filter (radius=%d) inside the mask" % radius,
          flush=True)
    filtered = itk.median_image_filter(image, radius=radius)

    mask = nonzero_mask(itk.array_view_from_image(labelmap))
    composed = composite_inside_mask(
        itk.array_view_from_image(image),
        itk.array_view_from_image(filtered),
        mask,
    )
    result = itk.image_from_array(composed)
    result.CopyInformation(image)  # keep spacing/origin/direction

    print("Writing %s" % args.outputVolume, flush=True)
    write_image(result, args.outputVolume)
    print("Done.", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--xml":
        xml_spec = os.path.splitext(sys.argv[0])[0] + ".xml"
        with open(xml_spec) as f:
            print(f.read())
        sys.exit(0)
    main(CLIArgumentParser().parse_args())
