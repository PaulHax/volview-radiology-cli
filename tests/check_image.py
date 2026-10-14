"""Check a built image's inventory, XML interfaces, and task isolation."""

import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree


def check_image(image, manifest_path, other_manifest_path):
    expected = json.loads(Path(manifest_path).read_text(encoding="utf8"))
    excluded = json.loads(Path(other_manifest_path).read_text(encoding="utf8"))

    def run(*arguments):
        return subprocess.run(
            ["docker", "run", "--rm", image, *arguments],
            check=False, text=True, capture_output=True,
        )

    listed = run("--list_cli")
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout) == expected, listed.stdout
    for name in expected:
        result = run(name, "--xml")
        assert result.returncode == 0, result.stdout + result.stderr
        assert ElementTree.fromstring(result.stdout).findtext("title").strip()
    for name in excluded:
        result = run(name, "--xml")
        assert result.returncode == 2, result.stdout + result.stderr
        assert "Unknown CLI" in result.stderr

    payload = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "python", image, "-c",
         ("import json; from pathlib import Path; "
         "print(json.dumps(sorted(p.name for p in Path('/opt/cli').iterdir() "
         "if p.is_dir() and (p / (p.name + '.xml')).exists())))")],
        check=True, text=True, capture_output=True,
    )
    assert set(json.loads(payload.stdout)) == set(expected), payload.stdout
    print(f"{image}: {len(expected)} tasks verified; other image's tasks excluded.")


if __name__ == "__main__":
    check_image(*sys.argv[1:])
