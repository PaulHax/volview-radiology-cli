# VolView Radiology CLI

A Docker image containing Slicer Execution Model jobs for Girder-VolView
segment measurements.

The image exposes these tasks through the `slicer_cli_web` `--list_cli`
interface:

- Generate Segment Rulers
- Export Segment Statistics

Development examples are packaged separately in `volview-cli-examples`:
Otsu Segmentation, Threshold Segmentation, Median Filter, and Masked Median
Filter. Register that image only where those example jobs are wanted.

## Build and inspect

```sh
docker build -t volview-radiology-cli:latest .
docker run --rm volview-radiology-cli:latest --list_cli

docker build --target examples -t volview-cli-examples:latest .
docker run --rm volview-cli-examples:latest --list_cli
```

## Published image

Every passing update to `main` creates the next patch tag and publishes the
radiology image to GitHub Container Registry. Merging a PR approves the release.
PR checks build and test both images without publishing.

A release such as `v0.2.1` publishes `ghcr.io/paulhax/volview-radiology-cli:0.2.1`
and a `sha-<commit>` tag. The current main release also updates `:main`, `:latest`,
and its major/minor aliases. Reruns reuse the assigned version; older runs do not
update those aliases.
Push an explicit `vMAJOR.MINOR.PATCH` tag for a minor or major release.
The examples image is built locally for development and E2E testing.
Select a numbered version for deployment, or pin its digest for exact repeatability:

```sh
docker pull ghcr.io/paulhax/volview-radiology-cli:0.2.1
```

The package must be public for anonymous pulls. If it is private, configure the
DSA Docker credentials before provisioning.

## Use with Girder-VolView

For a durable DSA installation, add the published image to the deployment's
provision YAML and re-run provisioning:

```yaml
slicer-cli-image:
  - ghcr.io/paulhax/volview-radiology-cli:0.2.1
```

The radiology image name stays the same and exposes only the two segment jobs.
Reimporting an updated tag removes its old example tasks. When changing version
tags, remove the retired image registration so its tasks do not remain listed.

See the Girder-VolView
[custom Slicer CLI guide](https://github.com/DigitalSlideArchive/girder_volview/blob/main/docs/custom-slicer-clis.md)
for the full authoring, verification, registry, and private-image workflow.

For local development without a registry, clone this repository, set `CLI_REPO`
in the Girder-VolView
development-stack `.env` file to that checkout, then run `script/deploy` (or
`script/ensure-radiology-cli`). The script builds the local image when needed
and registers its declared tasks with `slicer_cli_web`.
Use `script/ensure-radiology-cli --examples` to register the development image;
the E2E harness does this explicitly.

See the [Girder-VolView development documentation](https://github.com/DigitalSlideArchive/girder_volview/blob/main/docs/development.md#slicer-cli-images)
for the complete setup.

## Creating a CLI

Use the existing task whose input and output most closely match the new task as
the starting point. To add a task named `ExampleTask`:

1. Create `ExampleTask/ExampleTask.xml`. The Slicer Execution Model XML
   declares the title, parameters, and input/output channels that VolView and
   `slicer_cli_web` present to users. For a Girder-provided volume input, use
   `reference="_girder_id_"` so the task receives all file ids in a series.
2. Create `ExampleTask/ExampleTask.py`. It must print its sibling XML when run
   with `--xml`, parse the declared arguments with `CLIArgumentParser`, and
   write every declared output. Use `volview_cli_base.girder_input` to resolve
   Girder-backed inputs; use `assemble` for multi-file image series.
3. Add `"ExampleTask": {"type": "python"}` to `examples/cli_list.json`. The entry
   name must match both the directory and Python/XML basenames.
4. Add `COPY ExampleTask /opt/cli/ExampleTask/` to the Dockerfile's `examples`
   target.

Build the image and verify both the registration manifest and task interface:

```sh
docker build --target examples -t volview-cli-examples:latest .
docker run --rm volview-cli-examples:latest --list_cli
docker run --rm volview-cli-examples:latest ExampleTask --xml
pytest -q
```

With `CLI_REPO` pointed at this checkout, the Girder-VolView
`script/ensure-radiology-cli --examples` command builds a missing image and
registers every task declared in `examples/cli_list.json`. Rebuild an existing
image after changing its tasks.

## Segment jobs

Both jobs accept all painted label maps and optional saved annotations.
Embedded `.seg.nrrd` segment names match ruler labels; unnamed segments use
`Segment <value>`.

### Generate Segment Rulers

Adds two rulers on the image-aligned axial slice with the greatest long-axis
diameter: the longest chord and the widest extent perpendicular to it.
Both rulers use the segment name as their label. Any saved ruler associated
with a segment suppresses generation for that segment.

Ruler labels match segment names literally; suffixes have no special meaning.

The output contains only generated rulers. Saved annotations and label styles
are preserved. Use **Export Segment Statistics** for the CSV.

### Export Segment Statistics

Writes one CSV row per painted segment and unmatched ruler group:

- `input_image_path`: Girder item path; `segment_name`: segment name.
- `labelmap_index`: 1-based input map position, blank for unmatched groups.
- `volume_mm3`: segment volume; `warnings`: missing or invalid measurements.
- `intensity_min`, `intensity_max`, `intensity_mean`, `intensity_median`,
  `intensity_stddev`, `intensity_sum`: underlay statistics within the segment.
- `pet_intensity_min`, `pet_intensity_max`, `pet_intensity_mean`,
  `pet_intensity_median`, `pet_intensity_stddev`, `pet_intensity_sum`: PET layer
  statistics within the same segment, blank when no PET layer is supplied.
- `ruler_1_length_mm`, `ruler_2_length_mm`, etc.: ruler lengths, longest first.
  Columns extend to the largest ruler count.

Intensities use decoded voxels from the active view's base image.
Standard deviation is population standard deviation; sum is not volume-weighted.

Image and segmentation must share the same voxel grid. Unmatched ruler groups
have blank statistics. Invalid image values within a segment leave its
statistics blank with a warning.

VolView binds the first scalar image input to the base image and subsequent
scalar image inputs to attached layers in order. This report uses the first
attached layer as its optional PET input. Each input is one complete volume,
including every slice of a multi-file DICOM series.
This report declares `reference="_girder_id_"` and assembles each input's file
IDs separately. Custom CLIs must likewise handle a file list with that
declaration or `multiple="true"`; ordinary single-file image inputs cannot
receive a multi-file series.
The optional PET input (`--inputPETVolume`) may have different spacing, origin,
dimensions, and orientation. It must already be registered to the base image
in physical coordinates. PET values are linearly interpolated at segmentation
voxel centers. Centers outside the PET voxel-center extent are excluded with
a warning; a segment with no PET coverage has blank PET statistics. Invalid PET
values leave only that segment's PET statistics blank. Values use the decoded
image units, including DICOM rescale; no SUV conversion is performed. PET sum
adds interpolated values on the segmentation grid.

### Limitations

- Each segmentation input must be a complete scalar integer volume, such as
  `.seg.nrrd`.
- Use distinct segment names across inputs to avoid ambiguous ruler matching.

## DICOM slice inputs

A Girder DICOM series reaches the CLI as a comma-separated list of Girder file
ids, not as local paths. The input XML's `reference="_girder_id_"` preserves
those ids, while `slicer_cli_web` injects `girderApiUrl` and `girderToken`.
Use `resolve_inputs_to_local_paths` to download the files to the CLI's
temporary workspace, then pass the resulting paths to `assemble`.

`assemble` uses ITK's GDCM support and `ImageSeriesReader` to inspect DICOM
headers, sort slices by their recorded position, and construct one `itk.Image`
with the series geometry intact. Do not rely on the order of ids or filenames.
It rejects mixed inputs and multiple DICOM series rather than silently using a
partial volume.

## Tests

```sh
docker build --target test .
```

## License

MIT. See [LICENSE](LICENSE).
