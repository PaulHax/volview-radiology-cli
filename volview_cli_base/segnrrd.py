"""Write a labelmap as a compressed ``.seg.nrrd`` with embedded segment metadata.

The mirror of VolView's ``src/io/segNrrdMetadata.ts`` writer (Chunk 34): the
segment names/colors travel *inside* the labelmap file as Slicer-convention
``Segment{N}_*`` NRRD header fields, so the client recovers them on load (both
ends are ITK NRRD IO) and no separate JSON sidecar is paired by position.

Pure ITK — imports nothing from Girder — so it stays on the CLI's portable core.
``itk``'s NRRD writer serializes each ``MetaDataDictionary`` string entry into a
``key:=value`` header field; ``itk-wasm``'s ``readImage`` surfaces those fields
in the loaded image's metadata map, where ``parseSegNrrdMetadata`` picks them up.

``itk`` is imported lazily inside ``write_segmentation`` so the pure header
builder (``build_seg_metadata``/``_color_string``) — the half symmetric with the
client's ``parseSegNrrdMetadata`` — is importable and unit-testable with no itk
present (the offline gate has no itk, mirroring the itk-guarded filter tests).
"""


def _color_string(color):
    """RGB 0–255 (with optional alpha) -> Slicer's space-joined 0–1 floats."""
    r, g, b = color[0], color[1], color[2]
    return "%.6f %.6f %.6f" % (r / 255.0, g / 255.0, b / 255.0)


def build_seg_metadata(descriptors, dimensions):
    """Slicer-convention header fields for ``descriptors`` over a labelmap of
    ``dimensions`` (x, y, z).

    ``descriptors``: an ordered list of ``{"value", "name", "color": [r,g,b,...]}``
    (the same shape the retired JSON sidecar carried). ``Segment{N}`` uses the
    enumeration index N (0-based); ``LabelValue`` is the voxel value.
    """
    meta = {
        "Segmentation_MasterRepresentation": "Binary labelmap",
        "Segmentation_ContainedRepresentationNames": "Binary labelmap|",
        "Segmentation_ReferenceImageExtentOffset": "0 0 0",
    }
    extent = "0 %d 0 %d 0 %d" % (
        dimensions[0] - 1,
        dimensions[1] - 1,
        dimensions[2] - 1,
    )
    for index, descriptor in enumerate(descriptors):
        value = int(descriptor["value"])
        prefix = "Segment%d" % index
        meta[prefix + "_ID"] = "Segment_%d" % value
        meta[prefix + "_Name"] = str(descriptor["name"])
        meta[prefix + "_Color"] = _color_string(descriptor["color"])
        meta[prefix + "_LabelValue"] = str(value)
        meta[prefix + "_Layer"] = "0"
        meta[prefix + "_Extent"] = extent
        meta[prefix + "_Tags"] = "|"
    return meta


def write_segmentation(labelmap, path, descriptors):
    """Write ``labelmap`` (an ``itk.Image``) to ``path`` as a compressed
    ``.seg.nrrd`` carrying ``descriptors`` as embedded segment metadata."""
    import itk  # lazy: only the actual write needs itk (see module docstring)

    size = itk.size(labelmap)
    dimensions = [int(size[i]) for i in range(3)]
    metadata = build_seg_metadata(descriptors, dimensions)
    dictionary = labelmap.GetMetaDataDictionary()
    for key, value in metadata.items():
        dictionary[key] = value
    itk.imwrite(labelmap, str(path), compression=True)
