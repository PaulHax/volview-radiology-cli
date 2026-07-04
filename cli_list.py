import json
import os
import subprocess
import sys


def processCLI(filename):
    here = os.path.dirname(os.path.realpath(__file__))
    with open(os.path.join(here, filename)) as f:
        list_spec = json.load(f)

    if len(sys.argv) >= 2 and sys.argv[1] == "--list_cli":
        print(json.dumps(list_spec, sort_keys=True, indent=2, separators=(",", ": ")))
        return
    if len(sys.argv) < 2 or sys.argv[1][:1] == "-":
        print("%s --list_cli to get a list of available interfaces." % __file__)
        print("%s <cli> --help for more details." % __file__)
        return

    cli = os.path.normpath(sys.argv[1])
    if cli not in list_spec:
        sys.stderr.write(
            "Unknown CLI %r; run '%s --list_cli' for available interfaces.\n"
            % (sys.argv[1], __file__)
        )
        sys.exit(2)
    entry = list_spec[cli]
    cli = entry.get("alias", cli)
    script_file = os.path.join(here, cli, cli + ".py")
    # Propagate the child's exit code: a CLI that crashes (non-zero) must make
    # this dispatcher exit non-zero too, so girder_worker marks the job FAILED
    # instead of silently reporting success with no outputs.
    sys.exit(subprocess.call([sys.executable, script_file] + sys.argv[2:]))


if __name__ == "__main__":
    processCLI("cli_list.json")
