"""Otsu multi-threshold segmentation.

Produces a compressed ``.seg.nrrd`` labelmap with N+1 levels (0=background plus
N foreground labels). Each label's display name and RGB color travel *inside*
the file as Slicer-convention ``Segment{N}_*`` metadata, so the
client recovers them on load — no separate sidecar paired by position.
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

# A vivid, color-blind-friendly-ish palette. Index 0 is reserved for
# background, so we start label 1 at palette[0].
_PALETTE = [
    (231, 76, 60),    # red
    (52, 152, 219),   # blue
    (46, 204, 113),   # green
    (241, 196, 15),   # yellow
    (155, 89, 182),   # purple
    (26, 188, 156),   # teal
    (230, 126, 34),   # orange
    (236, 240, 241),  # off-white
]


def _label_name(value, num_levels):
    """Generate a short, sortable label name based on the value's bin."""
    if num_levels <= 4:
        # 2..4 levels: rough intensity descriptors.
        descriptors = ["lowest", "low", "mid", "high", "highest"]
        # value runs 1..num_levels (background=0 is omitted).
        idx = int(round((value - 1) * (len(descriptors) - 1) / (num_levels - 1)))
        return f"Region {value} ({descriptors[idx]})"
    return f"Region {value}"


def _build_label_descriptors(num_levels):
    descriptors = []
    for value in range(1, num_levels + 1):
        r, g, b = _PALETTE[(value - 1) % len(_PALETTE)]
        descriptors.append({
            "value": value,
            "name": _label_name(value, num_levels),
            "color": [r, g, b, 255],
        })
    return descriptors


def main(args):
    labelmap_path = args.outputLabelmap
    num_levels = int(args.numberOfLevels)
    api_url, token = resolve_girder_credentials(args)

    local_paths = resolve_inputs_to_local_paths(
        args.inputVolume, api_url=api_url, token=token
    )
    print(f"Assembling volume from {len(local_paths)} file(s)", flush=True)
    # Otsu wants a single-component, scalar image.
    image = to_scalar_float(assemble(local_paths))

    stats = itk.StatisticsImageFilter.New(image)
    stats.Update()
    in_min, in_max = stats.GetMinimum(), stats.GetMaximum()
    print(f"Input intensity range: [{in_min}, {in_max}]", flush=True)

    if in_max - in_min < 1e-6:
        print(
            "Constant-intensity input — emitting a single-label segmentation.",
            flush=True,
        )
        # Whole image labelled 1 (uint8, geometry preserved).
        labelmap = image.astype(itk.UC)
        itk.array_view_from_image(labelmap)[:] = 1
        num_levels = 1
    else:
        # Otsu accepts float inputs directly; no rescale needed.
        print(f"Running multi-Otsu with {num_levels} thresholds…", flush=True)
        otsu = itk.OtsuMultipleThresholdsImageFilter.New(image)
        otsu.SetNumberOfThresholds(num_levels)
        otsu.SetLabelOffset(0)
        otsu.Update()
        # Keep it small + signed-safe for downstream tools.
        labelmap = otsu.GetOutput().astype(itk.UC)

    descriptors = _build_label_descriptors(num_levels)
    print(f"Writing labelmap to {labelmap_path}", flush=True)
    write_segmentation(labelmap, labelmap_path, descriptors)

    print(f"Done. {num_levels} foreground labels emitted.", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--xml":
        xml_spec = os.path.splitext(sys.argv[0])[0] + ".xml"
        with open(xml_spec) as f:
            print(f.read())
        sys.exit(0)
    main(CLIArgumentParser().parse_args())
