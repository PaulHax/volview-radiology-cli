"""Resolve annotation and scalar label map inputs shared by the segment jobs."""

from volview_cli_base.annotations import SCHEMA_VERSION, SPACE, read_annotations
from volview_cli_base.assemble import assemble
from volview_cli_base.girder_input import resolve_inputs_to_local_paths
from volview_cli_base.segment_report import (
    image_metadata, pet_segment_intensities, segment_intensities, segment_names,
    voxel_summary,
)
from volview_cli_base.segment_rulers import labelmap_segments, reject_multi_file_dicom_series


def read_input_annotations(value, api_url, token):
    """Read the optional saved annotations, or an empty annotation collection."""
    if not str(value or "").strip():
        return {"schemaVersion": SCHEMA_VERSION, "space": SPACE, "tools": {}}
    local_paths = resolve_inputs_to_local_paths(value, api_url=api_url, token=token)
    if len(local_paths) != 1:
        raise ValueError("expected one annotations file, received %d" % len(local_paths))
    return read_annotations(local_paths[0])


def _labelmap_summary(path, underlay=None, pet=None):
    """Read one map's segment summaries without retaining voxels."""
    import itk

    image = assemble([path])
    if int(image.GetNumberOfComponentsPerPixel()) != 1:
        raise ValueError("input label map must have exactly one component per pixel")
    voxel_counts, voxel_volume_mm3 = voxel_summary(
        itk.array_view_from_image(image), image.GetSpacing()
    )
    metadata = image_metadata(image)
    segments = labelmap_segments(metadata, list(voxel_counts))
    names_by_value = segment_names(metadata) | {value: name for name, value in segments}
    return {
        "path": path,
        "segments": segments,
        "segment_names": list(names_by_value.values()),
        "voxel_counts": voxel_counts,
        "voxel_volume_mm3": voxel_volume_mm3,
        "intensity_stats": (
            segment_intensities(underlay, image, voxel_counts)
            if underlay is not None else {}
        ),
        "pet_intensity_stats": (
            pet_segment_intensities(pet, image, voxel_counts)
            if pet is not None else {}
        ),
    }


def read_labelmaps(value, api_url, token, underlay=None, pet=None):
    """Read scalar integer maps sequentially, retaining only paths and summaries."""
    paths = resolve_inputs_to_local_paths(value, api_url=api_url, token=token)
    reject_multi_file_dicom_series(paths)
    print("Reading %d label map(s)" % len(paths), flush=True)
    return [_labelmap_summary(path, underlay, pet) for path in paths]
