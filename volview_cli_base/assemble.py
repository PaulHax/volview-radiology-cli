"""Pure ITK volume assembly -- the shared, backend-agnostic core (D10).

``assemble(local_paths) -> itk.Image`` turns a set of on-disk files into one
volume. It is deliberately **pure**: it imports ``itk`` (and the standard
library) and **nothing from Girder** (AC2, the portability-containment pin), so
the v1->v2 migration (Option C: bind-mounted local paths) only deletes the
``girder_input`` download front-end and keeps this module untouched.

Geometry is the whole point of this module. A multi-slice DICOM series is
ordered by **metadata** (``GDCMSeriesFileNames`` sorts by the per-slice
``ImagePositionPatient`` projected on the slice normal) and read with
``ImageSeriesReader``, so inter-slice spacing and orientation come from the
DICOM headers -- never from the order the files happened to arrive in. This is
where the single-slice ``[1, 1, 1]`` spacing class of bug dies: the caller's
URI/path order and any advisory ``format`` tag are ignored for ordering; the
bytes decide.
"""

import os

import itk

# float32: exact for the int16 Hounsfield range typical of CT and general for
# any scalar acquisition, so the series path never needs a fragile per-file
# component-type sniff to stay lossless.
_SERIES_PIXEL_TYPE = itk.F
_SERIES_DIMENSION = 3


def _is_dicom(path):
    """Sniff bytes: does GDCM recognize this file as DICOM?

    Byte-level, not name-level -- a DICOM slice with no extension (the L3 layout,
    one file per item) still sorts into the series.
    """
    image_io = itk.GDCMImageIO.New()
    return bool(image_io.CanReadFile(str(path)))


def _common_directory(paths):
    absolute = [os.path.abspath(str(p)) for p in paths]
    directories = {os.path.dirname(p) for p in absolute}
    if len(directories) == 1:
        return directories.pop()
    return os.path.commonpath(absolute)


def _read_dicom_series(paths):
    """Metadata-sorted read of a multi-file DICOM series.

    ``GDCMSeriesFileNames`` scans the files' shared directory and returns each
    series' file names already ordered by slice position, so the reader stacks
    them with correct z-spacing/orientation regardless of input order. More than
    one series is an ambiguous input: rather than silently keep the first and
    drop the rest, fail closed. When the directory scan finds no series (unusual),
    fall back to the given files in a stable order so a result is still produced
    rather than nothing.
    """
    directory = _common_directory(paths)

    names = itk.GDCMSeriesFileNames.New()
    names.SetUseSeriesDetails(True)
    names.SetDirectory(directory)
    series_uids = list(names.GetSeriesUIDs())
    if len(series_uids) > 1:
        raise ValueError(
            "assemble: input spans %d DICOM series (%s); expected exactly one. "
            "Submit a single series per volume so slices are not silently dropped."
            % (len(series_uids), ", ".join(series_uids))
        )
    if series_uids:
        ordered = list(names.GetFileNames(series_uids[0]))
    else:
        ordered = [str(p) for p in sorted(paths)]

    image_type = itk.Image[_SERIES_PIXEL_TYPE, _SERIES_DIMENSION]
    reader = itk.ImageSeriesReader[image_type].New()
    reader.SetImageIO(itk.GDCMImageIO.New())
    reader.SetFileNames(ordered)
    # Keep the true acquisition frame (some ITK versions default to forcing an
    # orthogonal direction, which silently rewrites oblique geometry).
    if hasattr(reader, "ForceOrthogonalDirectionOff"):
        reader.ForceOrthogonalDirectionOff()
    reader.Update()
    return reader.GetOutput()


def assemble(local_paths):
    """Assemble on-disk files into a single ``itk.Image``.

    - A multi-file DICOM set -> metadata-sorted series read (the geometry-safe
      path).
    - A single DICOM file (multi-frame) or a single ``NRRD``/``NIfTI``/``MHA``/
      ... file -> a direct read (``itk.imread`` deduces the pixel type).
    - Anything else (e.g. several non-DICOM files) -> fail closed with a clear
      error rather than guess an assembly.
    """
    paths = [str(p) for p in (local_paths or [])]
    if not paths:
        raise ValueError("assemble: no input files given")

    dicom_paths = [p for p in paths if _is_dicom(p)]

    if dicom_paths and len(dicom_paths) == len(paths):
        if len(dicom_paths) == 1:
            # A single DICOM file is its own volume (multi-frame); imread reads
            # every frame, which ImageSeriesReader would not.
            return itk.imread(dicom_paths[0])
        return _read_dicom_series(dicom_paths)

    if len(paths) == 1:
        return itk.imread(paths[0])

    raise ValueError(
        "assemble: cannot assemble %d files; expected a single volume file or "
        "a DICOM series (got a mix of %d DICOM and %d non-DICOM files)"
        % (len(paths), len(dicom_paths), len(paths) - len(dicom_paths))
    )


def to_scalar_float(image):
    """Return a single-component float32 view of ``image`` (geometry preserved).

    The segmentation filters compute on a scalar float image. ``itk.Image``'s
    ``astype`` preserves spacing/origin/direction (it is a cast, not a NumPy
    round-trip). v1 inputs are scalar volumes; a genuinely multi-component
    input is out of scope and ITK will raise a clear cast error.
    """
    return image.astype(_SERIES_PIXEL_TYPE)


def write_image(image, path):
    """Write ``image`` to ``path``, creating parent directories, compressed."""
    directory = os.path.dirname(str(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    itk.imwrite(image, str(path), compression=True)
