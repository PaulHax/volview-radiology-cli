"""Turn rulers into native VolView rectangles."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volview_cli_base.annotations import (  # noqa: E402
    read_annotations,
    rulers_to_rectangles,
    write_annotations,
)
from volview_cli_base.cli import run  # noqa: E402
from volview_cli_base.girder_input import (  # noqa: E402
    resolve_girder_credentials,
    resolve_inputs_to_local_paths,
)


def main(args):
    api_url, token = resolve_girder_credentials(args)
    local_paths = resolve_inputs_to_local_paths(
        args.inputAnnotations, api_url=api_url, token=token
    )
    if len(local_paths) != 1:
        raise ValueError(
            "expected one annotations file, received %d" % len(local_paths)
        )

    annotations = read_annotations(local_paths[0])
    result = rulers_to_rectangles(annotations)
    write_annotations(result, args.outputAnnotations)
    print(
        "Wrote %d rectangle(s) to %s"
        % (len(annotations["tools"].get("rulers") or []), args.outputAnnotations),
        flush=True,
    )


if __name__ == "__main__":
    run(main)
