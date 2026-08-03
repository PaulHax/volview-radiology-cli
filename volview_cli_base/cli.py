"""The entry point every task script shares.

``slicer_cli_web`` discovers a task by running its script with ``--xml`` and
reading the spec it prints, then runs it again with the bound parameters. Both
halves live here so each task's ``__main__`` block is one line.
"""

import os
import sys

from slicer_cli_web import CLIArgumentParser


def run(main):
    """Print the calling script's XML spec for ``--xml``, else call ``main``.

    The spec is the ``.xml`` file sitting beside the script, so a task declares
    its parameters in one place.
    """
    if len(sys.argv) == 2 and sys.argv[1] == "--xml":
        xml_spec = os.path.splitext(sys.argv[0])[0] + ".xml"
        with open(xml_spec, encoding="utf-8") as spec:
            print(spec.read())
        sys.exit(0)
    main(CLIArgumentParser().parse_args())
