# Handwriting

An open-source tool for turning text and LaTeX math into handwritten-style PDFs.
Paste your notes or open a text/math file, choose a font, and save your PDF.
Processing happens locally on your computer.

## Install and open the app

Use Python 3.10 or newer:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
python app.py
```

On Windows, activate with `.venv\Scripts\activate` instead. The desktop app uses
Tkinter. If your Python installation does not include it, install your operating
system's Tkinter package (for example, `python3-tk` on Debian/Ubuntu), or use a
Python distribution that includes Tk.

1. Paste text into the editor or click **Open text / math file…**.
2. Choose a handwriting style and whether to use handwriting for math characters.
3. Click **Save handwritten PDF…**, then **Open PDF** to view or print it.

If your supplied `BigyanHand-A.ttf` (or `BigyanHand.ttf`) is present in
`custom_font/output/`, the app selects **My handwriting (Bigyan)** by default.
It also uses any B, C, and D font variants in that folder, along with their
adjacent `.handwriting.json` profiles, for your alternate letters, brackets,
and arrows. Leave **Use handwriting for math characters** enabled to use your
handwriting for equations too. Symbols absent from your samples stay typeset.
Square roots use the radical outline from your actual font; root bars and
fraction bars match the sample profile's pen weight. Letters inside roots,
summation signs, and integral signs also use your font when those glyphs exist.
The editor shows typed text; your handwriting appears in the saved PDF.
Personal font files stay local and are not included in the GitHub repository.
Without them, the app offers the bundled handwriting styles.

Supported inputs are UTF-8 `.txt`, `.md`, and `.tex` files containing prose and
LaTeX math snippets. Use `$...$` for inline math and `$$...$$` or fenced `math`
blocks for display equations. Full LaTeX documents (`\documentclass`, packages,
etc.), Word documents, PDFs, and images are not input formats. Markdown support
is limited to the parser's text and math conventions, not a full Markdown engine.
Unsupported handwritten symbols retain their typeset forms.

```text
The area of a circle is $A = \pi r^2$.

$$
x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}
$$
```

## Open source and contributions

You can use, modify, fork, redistribute, and contribute to the project under the
[MIT license](LICENSE). Keep its copyright and license notice with copies.
Bundled fonts and KaTeX retain their [third-party licenses](THIRD_PARTY_NOTICES.md).
See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, and pull requests.

## Command-line renderer

Turns a typed-up math solution (with LaTeX) into a natural-looking
"handwritten" PDF: ruled notebook paper, a handwriting font, subtle
per-word jitter so it doesn't read as a uniform font block, and real
typeset math (fractions, matrices, row reduction, boxed answers, etc.)
via KaTeX with a light hand-drawn wobble applied on top.

## Quick start

```bash
python3 handwrite.py input.txt output.pdf
```

That's it — `output.pdf` is ready to print.

Options:

```bash
python3 handwrite.py input.txt output.pdf \
  --font kalam \        # kalam (default) | indieflower | patrickhand |
                         # caveat | reeniebeanie | shadowsintolight | gochihand
  --seed 7 \             # change this to get a different jitter "handwriting pass"
  --clean \              # input is already clean LaTeX/Markdown -- skip the
                          # messy-paste cleanup pass (see below)
  --no-jitter \          # uniform font, no per-word wobble
  --keep-html out.html   # also save the intermediate HTML, useful for debugging
```

With a font built from your own handwriting (see `custom_font/`):

```bash
python3 handwrite.py input.txt output.pdf \
  --custom-font custom_font/output/BigyanHand.ttf \
  --font-size 30 --line-height 44 --hand-math
```

### Writing onto your own ruled page

```bash
python3 handwrite.py input.txt output.pdf \
  --custom-font custom_font/output/Hand-A.ttf \
  --custom-font-b custom_font/output/Hand-B.ttf \
  --paper my_goodnotes_page.pdf --hand-math
```

`--paper` takes a ruled page (PDF or image, e.g. exported from GoodNotes)
and writes onto it instead of generating ruled paper. It finds the page's
ruled lines automatically, matches the line spacing, lands the first
baseline on the first rule, clears the margin rule, and picks a font size to
suit the rule spacing (override with `--font-size`). Display math gets
padded out to a whole number of ruled lines so the prose after it lands back
on a line, and anything too wide for the column is stepped down to fit.

`--custom-font-b` is a second version of your handwriting: each character
randomly picks one of the two, so repeated letters aren't identical stamps.

`--hand-math` also renders the *math* in your handwriting instead of KaTeX's
typeset faces -- KaTeX still does all the layout (stretching brackets,
aligning matrix columns, drawing arrows), only the characters get swapped.
Accented things like `\vec x` stay typeset, because KaTeX positions the
arrow using its own font's metrics and a substituted font puts it in the
wrong place. Without the flag you get clean typeset math, which is correct
but reads as printed next to handwriting. `--font-size` matters here: a font
built from handwriting usually has a smaller x-height than the stock ones,
so it needs a larger size to match.

Run `python3 handwrite.py --help` any time for the full option list.

## Input format

Two ways to feed it text:

**Clean mode** (`--clean`): plain Markdown/LaTeX. Display math in
` ```math ... ``` ` fences or `$$...$$`, inline math in `$...$`. Everything
else is treated as normal prose (paragraph breaks = blank lines, plain
lines are just text).

**Messy-paste mode** (the default, no flag needed): handles the "flattened
duplicate" garbage that shows up when solutions get copied out of a
renderer that shows both a math image and its plain-text fallback back to
back — the ` ```math ``` ` fenced blocks are trusted as real LaTeX and kept
verbatim; everything else gets cleaned up: glued duplicate text right
after inline backtick math spans is stripped, standalone debris lines are
dropped, and a "truncated-copy-then-full-copy" glitch at the start of a
line is collapsed.

This cleanup is heuristic, not perfect. Every run prints cleanup notes to
the terminal, and any line where an artifact might still be lurking gets a
`WARNING: possible leftover artifact` note pointing at it — skim those
before you print/submit. The hardest case it can't fully solve: a
`\boxed{\text{...}}` (or any `\text{}`) that contains real prose sometimes
leaves a trailing duplicated clause behind, since there's no reliable way
to tell "duplicated echo" apart from "actually new sentence" once it's
made of real words instead of symbol soup. If you run into that a lot,
switch to clean mode and paste well-formed Markdown instead — much more
reliable.

## How it works / what to know about the output

- Body text renders in a handwriting font (Kalam by default) with small
  random per-word rotation, vertical offset, and ink-opacity variation, so
  it doesn't look like a uniform digital font.
- Math renders through KaTeX (real typesetting: fractions, matrices,
  augmented-matrix row reduction, `\boxed{}`, etc.) with a light SVG
  displacement filter for a hand-drawn wobble, rather than trying to force
  matrices into a shaky handwriting font (which doesn't typeset well and
  looks worse than clean math would).
- Pages are Letter-sized ruled paper with a left margin line; the ruled
  background tiles seamlessly across page breaks.
- `--seed` controls the jitter's randomness — same input + same seed always
  produces the identical PDF; change the seed for a different "pass."

## Files

- `handwrite.py` — the CLI / renderer (Python + Playwright + KaTeX)
- `clean.py` — the messy-paste cleanup + block parser (also has a
  `python3 clean.py` self-test against `example_input.txt`)
- `fonts/` — the handwriting fonts (Google Fonts, OFL licensed)
- `assets/katex/` — local KaTeX (no network needed at render time)
- `example_input.txt` — the sample you can test against

## Using your own handwriting instead of a stock font

See `custom_font/README.md` — write out a template in GoodNotes (or on
paper), and it gets traced into a real `.ttf` you can pass to `handwrite.py`
via `--custom-font path/to/YourFont.ttf` instead of `--font`.

## Requirements

Install dependencies with `python -m pip install -r requirements.txt` and the
browser with `python -m playwright install chromium`. Custom PDF paper backgrounds
also require Poppler's `pdfinfo` and `pdftoppm` on your PATH. Optional font-building
dependencies are listed in `custom_font/requirements-portable.txt`.

### Natural page layout

```bash
python3 handwrite.py hw_solutions.txt output/natural_handwriting.pdf --clean \
  --custom-font custom_font/output/BigyanHand-A.ttf \
  --custom-font-b custom_font/output/BigyanHand-B.ttf \
  --font-size 30 --line-height 44 --hand-math --analyze
```

The renderer measures fonts and equations locally in Chromium. It limits prose to
11 words per line (often fewer with long words or inline math), adds small line
and word variations, reserves 2–4 blank rules per page, and avoids starting a
problem in the last four writable lines. Short solutions stay together; longer
ones continue at prose-line or display-equation boundaries. Use explicit labels
such as `1.4 #14`, `Problem 1`, or `1.` to identify problems.

`--analyze` prints measured line density, equation breaks, page assignments and
warnings, and saves an adjacent `.layout.json`. This is a deterministic geometry
checker, not an LLM or a mathematical proofreader. The same `--seed` reproduces
the layout. `--no-jitter` disables writing jitter while retaining page margins.
Long chains split only at top-level relations, preserving nested LaTeX. An
indivisible expression that still exceeds the column is reported, never shrunk
into tiny text. Edit that expression before printing if a warning remains.

Add `--custom-font-c PATH --custom-font-d PATH` when the extra fonts are ready.
To retain square typeset brackets until you rewrite yours, use `--no-hand-delims`.
See `custom_font/README.md` for the new sample workflow.

Checks: `python3 -m unittest discover -s tests -v` and
`python3 tests/browser_layout.py` (requires a local Chromium/Chrome installation).

### Consistent pen weight and complete glyph selection

Mathematical square brackets now use centerlines extracted from your actual samples.
Only the middle stem extends as a matrix grows; stroke thickness stays calibrated
against the active handwriting fonts. `--bracket-stroke-scale 0.8` makes this pen
weight 20% thinner; the default `1.0` matches the measured reference weight.
`--no-hand-delims` still retains typeset delimiters.

With `--hand-math`, plain and vector letters use fonts that actually contain the
character. Vector arrows come from your arrow samples, and their position follows
the handwritten base. Visual aliases such as micro-sign `µ` and pasted mathematical
italic letters are recognized without changing the original LaTeX or semantic
MathML. Distinct mathematical alphabets such as blackboard bold retain their meaning.

`--analyze` includes a `handwriting` section with `fallbacks`, `structural`, `aliases`,
font-use counts, bracket pen widths, and vector sample choices. Missing characters
are retained and reported with their Unicode values and context. The supplied fonts
currently lack `#` and the em dash `—`; these remain explicit fallbacks. Structural
items that still require typeset geometry, such as non-vector accents, are identified
separately. Browser tests check actual selected fonts through Chromium, not just CSS.

The calibrated sample files are `custom_font/output/BigyanHand-*.handwriting.json`.
Keep these beside the TTFs when moving your fonts. They are embedded into saved HTML.
Regenerate a profile after changing letters or bracket/arrow samples, for example:

```bash
python3 custom_font/stroke_profiles.py --font custom_font/output/BigyanHand-A.ttf \
  --brackets custom_font/brackets_A --arrow custom_font/glyphs_math
```

Use brackets B for B/D and `glyphs_math2` for C/D. The profile generator requires
Pillow, NumPy, and fontTools; SciPy is optional. New checks:
`python3 tests/browser_handwriting.py` and `python3 tests/render_handwriting_comparison.py`.

### Using several handwritings

A *hand* is a directory of your own traced handwriting. Put one under
`~/.handwriting/hands/`, and the app offers it alongside the bundled styles:

```
~/.handwriting/hands/my-hand/
    hand.json     {"display": "My handwriting", "font_size": 30, "line_height": 44}
    A.ttf  B.ttf  C.ttf  D.ttf
```

Only `A` is required; B, C and D are alternate versions of the same hand, used
so repeated letters are not identical stamps. `hand.json` is optional — without
it the directory name is the display name. Variants may be named `A.ttf` or
`<Anything>-A.ttf`, and a single unsuffixed font counts as A, so fonts built by
`custom_font/` work unchanged. Set `HANDWRITING_HANDS` to read hands from
another directory as well. Personal hands are offered before the bundled ones,
so one of yours is selected by default.
