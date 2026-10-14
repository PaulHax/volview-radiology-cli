"""Export saved rulers, segment volumes, and source-image statistics."""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volview_cli_base.assemble import assemble  # noqa: E402
from volview_cli_base.cli import run  # noqa: E402
from volview_cli_base.girder_input import (  # noqa: E402
    resolve_girder_credentials,
    resolve_girder_item_path,
    resolve_inputs_to_local_paths,
)
from volview_cli_base.segment_inputs import (  # noqa: E402
    read_input_annotations,
    read_labelmaps,
)
from volview_cli_base.segment_rulers import (  # noqa: E402
    index_existing_rulers,
    orphan_rows,
    segment_rows,
    write_csv,
)


def main(args):
    api_url, token = resolve_girder_credentials(args)
    input_image_path = resolve_girder_item_path(
        args.inputVolume, api_url=api_url, token=token
    )
    underlay = assemble(resolve_inputs_to_local_paths(args.inputVolume, api_url, token))
    labelmaps = read_labelmaps(args.inputLabelmap, api_url, token, underlay=underlay)
    del underlay
    annotations = read_input_annotations(
        getattr(args, "inputAnnotations", ""), api_url, token
    )
    all_segments = [segment for labelmap in labelmaps for segment in labelmap["segments"]]
    painted_names = {name for name, _ in all_segments}
    name_counts = Counter(
        name for labelmap in labelmaps for name in labelmap["segment_names"]
    )
    existing = index_existing_rulers(annotations)
    rows = [
        row
        for index, labelmap in enumerate(labelmaps, start=1)
        for row in segment_rows(
            input_image_path,
            labelmap["segments"],
            existing,
            labelmap["voxel_counts"],
            labelmap["voxel_volume_mm3"],
            segment_name_counts=name_counts,
            labelmap_index=index,
            intensity_stats=labelmap["intensity_stats"],
        )
    ]
    rows.extend(
        orphan_rows(
            input_image_path, existing, painted_names,
            segment_name_counts=name_counts,
        )
    )
    write_csv(rows, args.outputReport)
    print(
        "Exported %d report row(s) across %d label map(s) to %s"
        % (len(rows), len(labelmaps), args.outputReport),
        flush=True,
    )


if __name__ == "__main__":
    run(main)
