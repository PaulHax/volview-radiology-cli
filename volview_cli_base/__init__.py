"""Shared image input and processing utilities for the radiology CLIs.

Two layers, kept apart on purpose:

- ``assemble`` provides volume assembly without Girder dependencies.
- ``girder_input`` resolves Girder file ids to local paths.

The two are imported separately so ``assemble`` never transitively pulls in a
Girder dependency; nothing here re-exports ``girder_input`` alongside
``assemble`` for that reason.
"""
