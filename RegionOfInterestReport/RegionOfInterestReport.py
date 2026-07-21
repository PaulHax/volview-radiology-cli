"""Generate a CSV summary of the regions in a scalar label map."""

import os
import sys

import itk
from slicer_cli_web import CLIArgumentParser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volview_cli_base.assemble import assemble  # noqa: E402
from volview_cli_base.girder_input import (  # noqa: E402
    resolve_girder_credentials,
    resolve_inputs_to_local_paths,
)
from volview_cli_base.roi_report import (  # noqa: E402
    image_metadata,
    report_rows,
    write_csv,
)


def main(args):
    api_url, token = resolve_girder_credentials(args)
    local_paths = resolve_inputs_to_local_paths(
        args.inputLabelmap, api_url=api_url, token=token
    )
    print(f"Reading label map from {len(local_paths)} file(s)", flush=True)
    labelmap = assemble(local_paths)
    if int(labelmap.GetNumberOfComponentsPerPixel()) != 1:
        raise ValueError("input label map must have exactly one component per pixel")

    array = itk.array_view_from_image(labelmap)
    spacing = [float(value) for value in labelmap.GetSpacing()]
    rows = report_rows(array, spacing, image_metadata(labelmap))
    write_csv(rows, args.outputReport)
    print(f"Wrote {len(rows)} region(s) to {args.outputReport}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--xml":
        xml_spec = os.path.splitext(sys.argv[0])[0] + ".xml"
        with open(xml_spec, encoding="utf-8") as spec:
            print(spec.read())
        sys.exit(0)
    main(CLIArgumentParser().parse_args())
