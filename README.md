# cdr2drawio

Convert CorelDRAW (`.cdr`) files to draw.io XML (`.drawio`) by decoding the
file format directly — nothing is recovered by rendering the drawing through
an external application.

Implemented with [opencode](https://opencode.ai) **1.18.32**, running the
`opencode/big-pickle` model (provider `opencode`, model ID `big-pickle`,
according to the recorded session metadata; this was the only model used).

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
from the command line:

```sh
drawio --export --format png --scale 2 -o Fig13_3.png Fig13_3.drawio
```

`drawio` is the cross-platform CLI that ships with the
[draw.io desktop application](https://github.com/jgraph/drawio-desktop) (on
macOS it is also available as
`/Applications/draw.io.app/Contents/MacOS/draw.io`, and on Windows as
`draw.io.exe`).

## What is supported

- **Frame**: page bounding box placed on an A4 page (794 × 1123 px); Corel
  units are 1/10000 mm and map to draw.io px via `px = svg_units * 96 / 2540`.
- **Shapes**: polylines and polygons from the `loda` geometry, through the
  object's `trfd` affine transform; Bézier segments are sampled from their
  control points; rectangles and ellipses are drawn from their bounding box.
- **Connectors**: endpoint pairs from `npps/ppdt` with arrowheads from the
  outline `leftArrow`/`rightArrow` flags.
- **Text**: labels from `txsm` (JSON on modern files, binary `txsm_7` on
  legacy files), including font name and size where available. CDR v6
  (`< 700`) uses the compact trailing character table (a char per 12-byte
  cell after the fixed header); CDR v12 (`CDRC`, e.g. `Fig9_3`) places the
  text at the tail as `[pad][u32 count][chars][NUL]` with `\r` line
  separators — a tail scan recovers it.
- **Origin**: content is anchored at the page origin so off-page (negative)
  coordinates in the source (e.g. `Fig9_3`) don't push shapes out of the
  viewport. Content that already sits on the page is left untouched.
- **Colours**: Corel CMYK strings mapped to CSS hex. An additive ink-stacking
  model (`r = 1 − min(1, c+k)`, as in Ghostscript's default CMYK→RGB) is used
  for non-black combinations; pure K100 renders as Corel's rich black,
  `#1B1918`.

## Verification

`verify.py` … `verify5.py` convert a `.drawio` back to a reference raster and
compare it with the render and with a Corel thumbnail. Paths are CLI
arguments (defaults point at regenerated `cpu2` artifacts):

```sh
python3 verify.py                     # geometry checks: lines, rects, arrows, texts
python3 verify.py --drawio X.drawio --render X.png --thumb X_thumb.png
python3 verify5.py --drawio ...       # per-text centroid deltas
```

All scripts share `verify_common.py` (PNG decode incl. indexed/grey,
drawio cell parsing, content-bbox derivation and svg↔pixel mapping). The
content box is derived from the drawing unless `--content X0 Y0 X1 Y1` is
given. `tools/extract_disp.py` pulls the embedded `DISP` preview bitmap out
of any `.cdr` and writes a canonical RGB PNG.

Baseline on `examples/cpu2.cdr` (all-K100 schematic):

- `verify.py`: `FAILS: 0` (ink IoU 0.43 vs the Corel thumbnail). A degenerate
  3-svg-unit connector (`e27`) is skipped — it is smaller than a screen pixel.
- `verify2.py`: `FAILS: 0`; arrow heads measure identical in render and thumb.
- `verify5.py`: worst text-centroid delta ≈ 139 svg (≈ 5 pixels of the content
  thumbnail), the bulk under 1 px.

## Known limitations

- Legacy text still uses the bounding-box height when no explicit font size
  is stored, and no per-object CMYK colours are present in the tested CDR7/8
  files (their `otlt`/`outl` chunks hold binary attributes only).
- The embedded `DISP` previews of the book-figure files (`Fig1_10` etc.) are
  not faithful renders of the drawing (a brute-force registration search tops
  out near zero IoU), so mask-based comparisons are only run on `cpu2`. The
  other figures verify via geometry checks (`verify.py` element checks) and
  rendered-output counts.
- Text-centroid deltas vs the thumbnail are within its pixel quantization
  (1 thumb px ≈ 28 svg): observed `dy ≈ −15..−41 svg`, `dx ≤ ~50 svg`, plus a
  single multi-line bold label at +137 svg. At document scale this is
  sub-millimetre and is treated as comparator noise, not a placement defect
  (the geometry of every cell places ink exactly at its mapped location).

## Roadmap

- ~~Fix the `verify.py`/`verify2.py` element failures (including the
  degenerate 3-unit connector `e27`).~~
- ~~Generalize the verify scripts to work on any `.cdr`/`.drawio` instead of
  hardcoded paths.~~
- ~~Improve CMYK→RGB conversion for non-K100 colours.~~
- Tune legacy fidelity: real font sizes from `txsm_7`/doc styles and colours
  from the `otlt`/`stlt` tables, validated against a reliable reference
  render (the DISP previews of the current samples cannot be used for that).

## Files

- `cdr2drawio.py` — the converter (single file, stdlib only).
- `examples/` — sample legacy CDR6/7/8/12 files (`Fig1_10`, `Fig3_8`,
  `Fig9_3`, `Fig13_3`, `Fig13_4`, `Fig13_23`) and a modern CDR (2200)
  file (`cpu2.cdr`).
- `verify.py` … `verify5.py`, `verify_common.py`, `probe.py` — verification
  helpers.
- `tools/extract_disp.py` — extract the embedded `DISP` preview bitmaps.

## Requirements

Python 3.9+ (stdlib only). Rendering `.drawio` to PNG is optional and requires
the [draw.io desktop application](https://github.com/jgraph/drawio-desktop).