"""Dependency-boundary tests that do not require ITK.

- Python sources and the Dockerfile do not depend on SimpleITK.
- The image installs ITK, and ``assemble`` has no Girder dependencies.
"""
import ast
import os
import re

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_THIS_FILE = os.path.abspath(__file__)
_SKIP_DIRS = {".git", "__pycache__", ".tox", ".venv", "venv", "node_modules",
              "fixtures"}


def _iter_py_files():
    for dirpath, dirnames, filenames in os.walk(_REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                path = os.path.join(dirpath, name)
                if os.path.abspath(path) != _THIS_FILE:
                    yield path


_SITK_TOKEN = re.compile(r"\bsitk\b")


def test_no_simpleitk_anywhere_in_python():
    offenders = []
    for path in _iter_py_files():
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if "simpleitk" in text.lower() or _SITK_TOKEN.search(text):
            offenders.append(os.path.relpath(path, _REPO_ROOT))
    assert not offenders, "SimpleITK/sitk still referenced in: %s" % offenders


def test_dockerfile_drops_simpleitk_and_installs_itk():
    with open(os.path.join(_REPO_ROOT, "Dockerfile"), encoding="utf-8") as fh:
        text = fh.read()
    assert "simpleitk" not in text.lower(), "Dockerfile still installs SimpleITK"
    assert re.search(r"\bitk==", text), "Dockerfile must pin the itk package"


def _imported_modules(source):
    tree = ast.parse(source)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.add(node.module)
    return modules


def test_assemble_has_no_girder_imports():
    assemble_path = os.path.join(_REPO_ROOT, "volview_cli_base", "assemble.py")
    with open(assemble_path, encoding="utf-8") as fh:
        modules = _imported_modules(fh.read())
    girderish = [
        m for m in modules
        if m.split(".")[0] in {"girder", "girder_client", "girder_volview",
                               "slicer_cli_web"}
    ]
    assert not girderish, "assemble must not import Girder: %s" % girderish
    # positive: it is ITK-backed.
    assert any(m.split(".")[0] == "itk" for m in modules)
