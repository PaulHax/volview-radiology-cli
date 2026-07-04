"""Shared CLI base for the VolView radiology CLIs (D10).

Two layers, kept apart on purpose:

- ``assemble`` -- pure ITK volume assembly, **no Girder imports** (AC2), the
  containment boundary that survives the v1->v2 migration.
- ``girder_input`` -- the v1 = b3 download front-end (``girder_client``), the
  thin layer deleted whole under v2 Option C.

The two are imported separately so ``assemble`` never transitively pulls in a
Girder dependency; nothing here re-exports ``girder_input`` alongside
``assemble`` for that reason.
"""
