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
- Ruler to Rectangle

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

The **Region of Interest Rulers** task finishes and checks a segment-group
annotation in one run. It takes the painted label map and whatever rulers are
already on the image, and returns two outputs: the rulers that were missing,
applied back onto the image, and a downloadable CSV.

It replaces the earlier volume-only Region of Interest Report task, whose six
region columns are the first six columns of this CSV.

### What it measures

For each nonzero label value it finds the axial slice where the region is
widest and measures two in-plane diameters there:

- `LD` -- the longest chord across the region on that slice.
- `SAD` -- the widest extent perpendicular to `LD` on that same slice.

The axial slices are the ones stacked along the image axis nearest to
superior-inferior, so a generated annotation's plane always aligns to an image
axis even when the volume was acquired obliquely. That is what the client
requires: it re-derives each tool's slice from `frameOfReference` and rejects
the whole result if a plane is oblique.

`LD` and `SAD` are label suffixes, not a claim about what the regions are. They
are ordinary planar shape descriptors, and the same convention serves any label
map whose segments are named.

### What it generates, and what it leaves alone

Rulers are labeled `<segment name> <kind>`, as in `n2 LD` and `n2 SAD`.
Embedded `.seg.nrrd` segment names supply the region names; other label-map
formats receive deterministic names such as `Region 1`.

A region that already carries a ruler for a measurement keeps it. Nothing
already placed is regenerated, moved, or replaced, so re-running the task after
an annotator has filled in the gaps generates nothing and only re-reports. The
output is additive and carries only the rulers this run created; input tools
are never echoed. A label the input file already defines keeps its own style,
so a re-run never restyles an annotator's labels.

### What it checks

The CSV reports one row per painted region and one row per ruler no region
claims. The `warnings` column explains any problem in plain language, including
the offending ruler or segmentation label. It reports unmatched and unparsed
ruler labels, duplicate measurements or segment names, empty segments, and
measurements that are neither placed nor derivable. A clean row has an empty
`warnings` value.

The audit accepts the separators seen in hand-annotated sessions and is
case-insensitive on the kind, so an existing `n2-ld` still joins to segment
`n2` rather than being reported as an orphan.

### Running it without any annotations

The annotations input is declared with a `<longflag>` rather than an `<index>`,
which makes it optional. This is deliberate: an image whose regions carry no
rulers yet is the task's primary case, and VolView binds an annotations input
only once the image has a finished annotation. An indexed -- and therefore
required -- input would make the form refuse to run in exactly that case. An
absent argument means "nothing placed yet", a starting state rather than an
error.

## Ruler to Rectangle

The **Ruler to Rectangle** task uses each ruler's endpoints as the opposite
corners of a rectangle. It omits source annotations because outputs are
additive.

The Slicer Execution Model has no vector-annotation element, so both sides are
`<file>` parameters whose `fileExtensions` declares `.annotations.json`. That
declaration is the only signal Girder-VolView reads: an input so declared is
bound to the annotations on the active image, and an output so declared is
applied back onto it.

The file is a versioned envelope whose coordinates are world LPS millimetres,
never image indices. `volview_cli_base.annotations` reads and writes it,
fail-closed: an unrecognized `schemaVersion` or `space`, a tool without a frame
of reference, a session-only field such as `id` or `color`, or a label name that
its tool kind's namespace does not declare all reject the whole file. The
normative definition is the `volview` package's backend contract, and the
Girder-VolView
[custom Slicer CLI guide](https://github.com/DigitalSlideArchive/girder_volview/blob/slicer-cli-docs/docs/custom-slicer-clis.md)
documents the format for authors.
The Python checks here are only a small runtime guard for clear job failures;
they are not a second contract authority, and format changes begin in VolView.

Rectangle edges follow the referenced image's in-plane axes. Use a polygon for
a rotated box.

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
