# VolView Radiology CLI

A small Docker image containing Slicer Execution Model command-line modules
used to drive Girder-VolView radiology processing during development and
end-to-end testing. It is reference and example infrastructure for the
Girder-VolView integration.

The image exposes these tasks through the `slicer_cli_web` `--list_cli`
interface:

- Otsu Segmentation
- Threshold Segmentation
- Median Filter
- Masked Median Filter
- Region of Interest Rulers

## Build and inspect

```sh
docker build -t volview-radiology-cli:latest .
docker run --rm volview-radiology-cli:latest --list_cli
```

## Published image

Release tags publish the image to the GitHub Container Registry. A tag such as
`v0.1.0` produces `ghcr.io/paulhax/volview-radiology-cli:0.1.0` and `:latest`.
Pull an immutable version for a deployment:

```sh
docker pull ghcr.io/paulhax/volview-radiology-cli:0.1.0
```

The package must be public for anonymous pulls. If it is private, configure the
DSA Docker credentials before provisioning.

## Use with Girder-VolView

For a durable DSA installation, add the published image to the deployment's
provision YAML and re-run provisioning:

```yaml
slicer-cli-image:
  - ghcr.io/paulhax/volview-radiology-cli:0.1.0
```

See the Girder-VolView
[custom Slicer CLI guide](https://github.com/DigitalSlideArchive/girder_volview/blob/main/docs/custom-slicer-clis.md)
for the full authoring, verification, registry, and private-image workflow.

For local development without a registry, clone this repository, set `CLI_REPO`
in the Girder-VolView
development-stack `.env` file to that checkout, then run `script/deploy` (or
`script/ensure-radiology-cli`). The script builds the local image when needed
and registers its declared tasks with `slicer_cli_web`.

See the [Girder-VolView development documentation](https://github.com/DigitalSlideArchive/girder_volview/blob/main/docs/admin.md#local-reference-image)
for the complete setup.

## Creating a CLI

Use the existing task whose input and output most closely match the new task as
the starting point. A task named `ExampleTask` has three required pieces:

1. Create `ExampleTask/ExampleTask.xml`. The Slicer Execution Model XML
   declares the title, parameters, and input/output channels that VolView and
   `slicer_cli_web` present to users. For a Girder-provided volume input, use
   `reference="_girder_id_"` so the task receives all file ids in a series.
2. Create `ExampleTask/ExampleTask.py`. It must print its sibling XML when run
   with `--xml`, parse the declared arguments with `CLIArgumentParser`, and
   write every declared output. Use `volview_cli_base.girder_input` to resolve
   Girder-backed inputs; use `assemble` for multi-file image series.
3. Add `"ExampleTask": {"type": "python"}` to `cli_list.json`. The entry
   name must match both the directory and Python/XML basenames.

Build the image and verify both the registration manifest and task interface:

```sh
docker build -t volview-radiology-cli:latest .
docker run --rm volview-radiology-cli:latest --list_cli
docker run --rm volview-radiology-cli:latest ExampleTask --xml
pytest -q
```

With `CLI_REPO` pointed at this checkout, the Girder-VolView
`script/ensure-radiology-cli` command rebuilds the image when needed and
registers every task declared in `cli_list.json`.

## Region of Interest Rulers

The **Region of Interest Rulers** task takes a painted label map plus whatever
rulers are already on the image, and returns the rulers that were missing --
applied back onto the image -- and a downloadable CSV.

For each nonzero label value it finds the axial slice where the region is
widest and measures two in-plane diameters there:

- `LD` -- the longest chord across the region on that slice.
- `SAD` -- the widest extent perpendicular to `LD`.

Axial slices are the ones stacked along the image axis nearest to
superior-inferior, so a generated plane stays aligned to an image axis even for
an obliquely acquired volume, as the client requires. `LD` and `SAD` are label
suffixes, not a claim about what the regions are; they are ordinary planar
shape descriptors.

Rulers are labeled `<segment name> <kind>`, as in `n2 LD`. Embedded `.seg.nrrd`
segment names supply the region names; other label-map formats receive
deterministic names such as `Region 1`. A region that already carries a ruler
keeps it, so re-running after an annotator fills in the gaps generates nothing.
The output is additive: it carries only the rulers this run created, and a
label the input already defines keeps its own style.

The CSV has one row per painted region and one row per ruler no region claims:
`input_image_path`, `roi_name`, `ld_length_mm`, `sad_length_mm`, `volume_mm3`,
and `warnings`. `input_image_path` names the Girder item holding the input
image or DICOM series, never the temporary label-map or annotation inputs.
`warnings` is empty on a clean row and otherwise explains the problem in plain
language -- unmatched or unparsed ruler labels, duplicate measurements or
segment names, empty segments, and measurements neither placed nor derivable.
The audit is case-insensitive and tolerant of separators, so an existing
`n2-ld` joins to segment `n2` rather than being reported as an orphan.

The annotations input uses a `<longflag>` rather than an `<index>`, which makes
it optional: an image whose regions carry no rulers yet is the task's primary
case, and VolView binds an annotations input only once the image has a finished
annotation.

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
pytest -q
```

## License

MIT. See [LICENSE](LICENSE).
