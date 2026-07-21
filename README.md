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
- Region of Interest Report

## Build and inspect

```sh
docker build -t volview-radiology-cli:latest .
docker run --rm volview-radiology-cli:latest --list_cli
```

## Use with Girder-VolView

Clone this repository locally, set `CLI_REPO` in the Girder-VolView
development-stack `.env` file to that checkout, then run `script/deploy` (or
`script/ensure-radiology-cli`). The script builds the local image when needed
and registers its declared tasks with `slicer_cli_web`.

See the [Girder-VolView development documentation](https://github.com/PaulHax/girder_volview/blob/just-jobs/docs/development.md#radiology-cli-task-image)
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

## Region of Interest report

The **Region of Interest Report** task accepts a scalar integer label map and
returns a downloadable CSV. Zero is treated as background; every distinct
nonzero value produces one row containing the region name, label value, voxel
count, voxel volume, and total volume in cubic millimetres and millilitres.

For `.seg.nrrd` inputs, embedded Slicer segment names are used. Other label-map
formats receive deterministic names such as `Region 1`. The calculation depends
only on label values, image spacing, and optional embedded segment names.

Rulers are not included because they are stored in the VolView session manifest,
not in the label map passed to a Slicer CLI. Supporting them requires a separate
serialized annotation input from Girder-VolView.

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
