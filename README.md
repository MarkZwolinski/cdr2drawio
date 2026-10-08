# cdr2drawio

Convert CorelDRAW (`.cdr`) files to draw.io XML (`.drawio`) by decoding the
file format directly — nothing is recovered by rendering the drawing through
an external application.

The container is parsed by hand (no third-party libraries):

- **modern ZCF container**: a ZIP whose `content/root.dat` is a RIFF `CDR*`
  object directory and `content/data/page1.dat` holds the payload stream.
- **legacy containers**: the `.cdr` file is itself a RIFF body (`CDR7`,
  `CDR8`), with inline leaf payloads. Very old files may compress the whole
  body into a top-level `LIST cmpr` (two zlib `CPng` streams).

## Usage

```sh
python3 cdr2drawio.py <input.cdr> <output.drawio>
```

Both arguments are optional; the diagram name is derived from the input
filename.

### Example

```sh
python3 cdr2drawio.py examples/Fig13_3.cdr Fig13_3.drawio
```

Open the `.drawio` file in [draw.io](https://app.diagrams.net) or render it
with the draw.io desktop CLI:

```sh
/Applications/draw.io.app/Contents/MacOS/draw.io -x -f png -s 2 \
  -o Fig13_3.png Fig13_3.drawio
```

## What is supported

- **Frame**: page bounding box placed on an A4 page (794 × 1123 px); Corel
  units are 1/10000 mm and map to draw.io px via `px = svg_units * 96 / 2540`.
- **Shapes**: polylines and polygons from the `loda` geometry, through the
  object's `trfd` affine transform; Bézier segments are sampled from their
  control points; rectangles and ellipses are drawn from their bounding box.
- **Connectors**: endpoint pairs from `npps/ppdt` with arrowheads from the
  outline `leftArrow`/`rightArrow` flags.
- **Text**: labels from `txsm` (JSON on modern files, binary `txsm_7` on
  legacy files), including font name and size where available.
- **Colours**: Corel CMYK strings mapped to CSS hex (pure K100 renders as
  Corel's rich black, `#1B1918`).

## Known limitations

- Legacy text uses the bounding-box height when no explicit font size is
  stored, and colours are not yet pulled from the legacy `otlt`/`stlt` style
  tables.
- Text placement has a small vertical bias (`~30` svg units).
- `verify.py`/`verify2.py` still report a handful of element-level failures
  (e.g. a degenerate 3-unit connector) that predate this tool's feature work.

## Roadmap

- Fix the text-placement bias (~30 svg vertical offset; worst observed
  centroid delta 139 svg).
- Fix the `verify.py`/`verify2.py` element failures (including the degenerate
  3-unit connector `e27`).
- Generalize the verify scripts to work on any `.cdr`/`.drawio` instead of
  hardcoded paths.
- Tune legacy fidelity: real font sizes from `txsm_7`/doc styles and colours
  from the `otlt`/`stlt` tables, validated against the DISP thumbnail.
- Improve CMYK→RGB conversion for non-K100 colours.

## Files

- `cdr2drawio.py` — the converter (single file, stdlib only).
- `examples/` — sample legacy CDR7/CDR8 files (`Fig1_10`, `Fig13_3`,
  `Fig13_4`, `Fig13_23`).
- `verify.py` … `verify5.py`, `probe.py` — pixel-based verification helpers.

## Requirements

Python 3.9+ (stdlib only). Rendering `.drawio` to PNG is optional and requires
the [draw.io desktop application](https://github.com/jgraph/drawio-desktop).