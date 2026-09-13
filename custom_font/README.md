# Build a font from your own handwriting

Traces a filled-in template into a real `.ttf`, which plugs into
`../handwrite.py` via `--custom-font`.

## Templates

| File | What it is |
|---|---|
| `output/template.pdf` | Set 1 — a-z, A-Z, 0-9, punctuation (76 boxes) |
| `output/template_set2.pdf` | Set 2 — the same 76 characters again, a second version of each |
| `output/template_math.pdf` | Math — brackets, operators, Greek, symbols (70 boxes) |

Each has a matching `manifest*.json` recording exact box positions — keep
them together, extraction needs them.

## 1. Fill one out

Import the PDF into GoodNotes as the page background, write each character
**once** inside its box sitting on the solid blue baseline, dark pen. Then
**File → Export → PDF**, all pages, page size unchanged.

- **Set 2:** write naturally, don't try to copy your set 1 shapes — the
  point is that they differ.
- **Math:** skip any symbol you never use. Blank boxes are fine; those
  characters just stay typeset. Brackets marked "draw tall" should fill the
  box top to bottom — they get stretched to fit around matrices.

## 2. Build

```bash
# extract each filled page into its own glyph directory
python3 extract_glyphs.py filled_set1.pdf output/manifest.json       glyphs_set1/
python3 extract_glyphs.py filled_set2.pdf output/manifest_set2.json  glyphs_set2/
python3 extract_glyphs.py filled_math.pdf output/manifest_math.json  glyphs_math/

# variant A: set 1 + math, and save the metrics
python3.12 build_font.py output/Hand-A.ttf \
    --glyphs glyphs_set1 --glyphs glyphs_math \
    --name "Bigyan Hand" --metrics-out output/metrics.json

# variant B: set 2 + math, reusing A's metrics so both are the same size
python3.12 build_font.py output/Hand-B.ttf \
    --glyphs glyphs_set2 --glyphs glyphs_math \
    --name "Bigyan Hand B" --metrics-in output/metrics.json
```

`--metrics-in` matters: without it each build calibrates its own scale from
its own letters, and the two variants would come out slightly different
sizes — visible as letters jumping around mid-word.

`build_font.py` **must** run under `python3.12` (that's the interpreter the
`fontforge` module is built against here); plain `python3` fails with
`ModuleNotFoundError: fontforge`.

## 3. Use

```bash
python3 ../handwrite.py in.txt out.pdf \
    --custom-font custom_font/output/Hand-A.ttf \
    --custom-font-b custom_font/output/Hand-B.ttf \
    --hand-math
```

With `--custom-font-b`, each character randomly picks one of the two
versions, in the prose and inside the math.

## How it works

`extract_glyphs.py` rasterizes the filled PDF, crops each box using exact
coordinates from the manifest, thresholds out everything but dark ink (the
printed guides are all light enough to fall outside the threshold), and
crops tight around what's left.

`build_font.py` scales every glyph by one shared factor — so the natural
size differences between your letters survive — places each on the baseline
by what kind of character it is, vectorizes with `potrace`, and imports the
outline into a FontForge glyph. Advance widths come from each glyph's own
ink width, so `i` doesn't take as much room as `m`.

Vertical placement is **not** taken from where you wrote in the box. People
don't write exactly on the guide line, and in practice the offsets spanned
80+ px, which renders as badly bouncing text. Instead each character is
placed by its type: sits on the baseline; hangs below it (g j p q y , ;);
hangs from the cap line (quotes, degree, prime); or centres on the x-height
(− × ÷ ± ≠ ≤ ≥ arrows …). Delimiters are normalised to a fixed height of
their own and excluded from the shared scale — otherwise one tall bracket
would shrink the whole alphabet.

## Limitations

- No kerning (pair-specific spacing) — advance widths only.
- Only the characters on the templates.
- Faint strokes can fall below the ink threshold; if a character comes out
  broken, rewrite it bolder and re-export.

### Extra samples and bracket replacement

From the project root, generate the new templates:

```bash
python3 custom_font/bracket_template_gen.py output/template_brackets.pdf output/manifest_brackets.json
python3 custom_font/template_gen_extended.py --output-dir output
```

Write two bracket pairs on the single bracket page, and fill `template_set3.pdf`,
`template_set4.pdf`, and `template_math2.pdf`. Export each filled template at its
original page size, in its original page order. Keep its matching manifest.

Extract the bracket samples into separate directories (canonical character names
are shared between variants, so the font builder can replace the old brackets):

```bash
python3 custom_font/extract_glyphs.py filled_brackets.pdf output/manifest_brackets.json custom_font/brackets_A --variant A
python3 custom_font/extract_glyphs.py filled_brackets.pdf output/manifest_brackets.json custom_font/brackets_B --variant B
python3 custom_font/extract_glyphs.py filled_set3.pdf output/manifest_set3.json custom_font/glyphs_set3
python3 custom_font/extract_glyphs.py filled_set4.pdf output/manifest_set4.json custom_font/glyphs_set4
python3 custom_font/extract_glyphs.py filled_math2.pdf output/manifest_math2.json custom_font/glyphs_math2
```

Build all variants using A's existing shared metrics. Earlier glyph directories
win on duplicate characters, so put replacement brackets first. For example:

```bash
python3.12 custom_font/build_font.py custom_font/output/BigyanHand-C.ttf \
  --glyphs custom_font/brackets_A --glyphs custom_font/glyphs_set3 \
  --glyphs custom_font/glyphs_math2 --name 'Bigyan Hand C' \
  --metrics-in custom_font/output/metrics.json
python3.12 custom_font/build_font.py custom_font/output/BigyanHand-D.ttf \
  --glyphs custom_font/brackets_B --glyphs custom_font/glyphs_set4 \
  --glyphs custom_font/glyphs_math2 --name 'Bigyan Hand D' \
  --metrics-in custom_font/output/metrics.json
```

Rebuild A/B the same way with `glyphs` / `glyphs_set2` and `glyphs_math`, putting
`brackets_A` / `brackets_B` first. Two new bracket samples give two distinct bracket
shapes; the second math set gives two shapes per math symbol, while letters and
numbers can have four. Sharing a math set across fonts does not create new shapes.
The font builder requires FontForge, potrace, and its compatible Python interpreter;
extraction requires Poppler's `pdftoppm` on PATH.

### Adding the missing # character

The two-box sheet is `output/template_hash.pdf`, with `output/manifest_hash.json`.
Fill both boxes at your normal letter size and export the whole page into `my_font`.
Generate another blank copy with `python3 custom_font/supplemental_template_gen.py`.
The completed earlier sheets and manifests are unchanged; future alphabet templates
append `#` after all existing characters.

Extract the new samples independently:

```bash
python3 custom_font/extract_glyphs.py my_font/filled_hash.pdf output/manifest_hash.json custom_font/hash_A --variant A
python3 custom_font/extract_glyphs.py my_font/filled_hash.pdf output/manifest_hash.json custom_font/hash_B --variant B
```

Patch sample A into fonts A/C and sample B into B/D. For example, create a new A:

```bash
python3 custom_font/build_font.py custom_font/output/updated/BigyanHand-A.ttf \
  --backend portable --base-font custom_font/output/BigyanHand-A.ttf \
  --glyphs custom_font/hash_A --metrics-in custom_font/output/metrics.json \
  --metrics-font custom_font/output/BigyanHand-A.ttf
```

The portable patcher adds absent Unicode characters and preserves existing glyph
outlines and mappings. Inspect the result before replacing your previous font.
Keep its `.handwriting.json` sidecar alongside it; adding only `#` does not change
bracket/arrow geometry or the existing letter-based pen calibration.
