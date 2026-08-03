"""Filesystem helpers shared by this package's writers."""

import os


def ensure_parent_directory(path):
    """Create the directory ``path`` will be written into, if it has one."""
    parent = os.path.dirname(str(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
