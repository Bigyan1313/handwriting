# Architecture

How the renderer is put together, why the main decisions were made, and where
the current design will run out of room. Written for someone about to change
the code. For usage see [README.md](../README.md); for setup and pull requests
see [CONTRIBUTING.md](../CONTRIBUTING.md).

## The core idea

The renderer does not compute glyph metrics in Python and hope the output
matches. It builds one self-contained HTML document, opens it in headless
Chromium, and **measures the real rendered geometry** — ink extents from canvas
metrics, boxes from the live DOM — then makes every line-breaking and
pagination decision from those measurements before printing to PDF.

Chromium is the measuring instrument, not just a viewer. That is why layout
lives in JavaScript rather than Python, and why rendering blocks on
`window.__renderDone`.

A second idea shapes the handwriting: a handwriting *font* is not handwriting.
Repeated letters from a font are identical stamps, and real writing is not. So
the renderer accepts up to four variants of the same hand, chooses between them
per character from a seeded generator, and adds per-word rotation, vertical
offset and ink-opacity variation on top. The same input and `--seed` always
reproduce the same PDF.

## Pipeline

```
input.txt ──▶ clean.py ──▶ handwrite.py ──▶ ┌── headless Chromium ──┐ ──▶ output.pdf
              repair       build_html()     │ 1 KaTeX typesets math │
              + parse      (one HTML        │ 2 handwriting.js      │
                            string)         │   swaps glyphs        │
                                            │ 3 layout.js measures  │
                                            │   and paginates       │
                                            │ 4 page.pdf()          │
                                            └───────────┬───────────┘
                                                        │
                        window.__layoutReport ──────────┘
                        (page fill, line density, overwide
                         equations, glyph fallbacks)
```

The return path is the unusual part. Chromium hands measured geometry back to
Python, which surfaces it through `--analyze` and as render warnings. That is
what makes the layout auditable rather than only visual.

**Python to browser** is a single HTML string with everything embedded: fonts as
base64 data URIs, KaTeX, glyph coverage sets, and sample-derived stroke profiles
as JSON. **Browser to Python** is one JSON object, `window.__layoutReport`.

## Modules

| File | Lines | Responsibility |
|---|---|---|
| `handwrite.py` | 731 | CLI, font embedding, paper geometry, the HTML document template, Playwright driving. About half is one f-string. |
| `clean.py` | 296 | Messy-paste repair, block parsing, inline segmentation, safe equation splitting. Pure functions, no I/O. |
| `handwriting.js` | 269 | Per-glyph font selection from coverage sets; redraws brackets, vector arrows and radicals as SVG; writes the handwriting audit. |
| `app.py` | 194 | Tkinter editor. Renders on a worker thread, polls a queue, surfaces cleanup notes as a warning dialog. |
| `layout.js` | 173 | Equation line-splitting, word-atom line breaking, pagination with widow control, the layout report. |
| `paper.py` | 114 | Rasterize a page, find ruled lines and the margin rule by pixel coverage, return resolution-independent fractions. |
| `custom_font/` | ~630 | Charset definitions, template generators, glyph extraction, two font-building backends, stroke-profile calibration. |
| `tests/` | 516 | Three unit modules, two browser suites, one visual-acceptance PDF generator. |

Dependencies are deliberately thin: Playwright drives Chromium, fontTools reads
vertical metrics and glyph outlines, Pillow and NumPy do ruled-line detection
and stroke analysis, and KaTeX is vendored locally so rendering never touches
the network. No web framework, no build step, no bundler.

## Decisions worth knowing before you change things

**Measure, never predict.** Geometry work waits on `withFontsLoaded()`, which
explicitly loads each family before measuring. `document.fonts.ready` can
resolve before the browser has requested a face it has not laid out, which
silently falls back to a default face and poisons canvas metrics.

**Glyphs are placed by character class, not by where they were written.** In
`build_font.py`, vertical placement comes from what kind of character it is:
sits on the baseline, descends (`g j p q y`), hangs from the cap line (quotes,
prime), or centres on the x-height (operators, arrows). Using the written
position spanned 80+ pixels of offset and rendered as badly bouncing text.
Delimiters are scaled separately, or one tall bracket shrinks the whole
alphabet.

**Matrices are not forced into a shaky font.** KaTeX keeps all structural
layout; only characters are swapped. Brackets are the exception — KaTeX draws
tall delimiters as SVG paths rather than glyphs, so they cannot be font-swapped.
Instead the delimiter is read out of the LaTeX source in order, its box is
measured, and a traced centreline is scaled to cover it.

## Known structural weak point

The three JavaScript layers share implicit globals:

- `handwriting.js` calls `origInk()` and `delimsFromTex()`, which are defined in
  the f-string inside `handwrite.py`.
- `layout.js` calls `mkRand()` from the same place, and its first line runs
  before that function textually appears — it works only because function
  declarations hoist.
- `handwriting.js` writes into `layoutReport`, a `const` owned by `layout.js`.

None of the three can be loaded or tested on its own. Extracting the embedded
delimiter JavaScript into its own file (the pattern `layout.js` and
`handwriting.js` already follow) resolves this.

## Scaling

Nothing here is architecturally wrong, but nearly every path assumes *one user
rendering one document interactively*. That shows up as process startup per
render, repeated work that could be cached, and a layout loop with a much worse
constant factor than it needs.

### A. Make one render fast

- **Keep the browser alive.** `main()` opens `sync_playwright()`, launches
  Chromium, renders one document and tears it all down; the desktop app wraps
  that in a fresh Python subprocess per save. Lifting the browser into a
  reusable renderer object removes the per-document startup cost.
  (`handwrite.py`, `app.py`)
- **Stop re-encoding fonts every render.** `_face()` base64-encodes each TTF and
  `font_resources()` reopens each with fontTools to rebuild its coverage string
  on every render. With four variants that is several megabytes regenerated per
  document. Memoize on path plus mtime. (`handwrite.py`)
- **Fix the layout thrash.** The line-breaking loop appends a word then
  immediately calls `getBoundingClientRect()`, forcing a synchronous reflow per
  word. Measure all atoms once and place them arithmetically, or batch through
  `Range.getClientRects()`. (`layout.js`)

### B. Handle bigger documents

- **Chunk by problem group and concatenate PDFs.** Memory and layout time grow
  with document length because everything lives in `#source` at once. The block
  model already groups content independently. Page numbering and the
  blank-top-lines randomisation need to carry across chunks.
- **Reclaim wasted page space.** The bundled sample renders both pages 64% full
  at 6.4 words per line. The 11-word cap combined with the right padding leaves
  a narrow, ragged column; the cap would be better derived from measured column
  width than fixed.

### C. Render more kinds of input

- **Replace the line-based parser with a real Markdown AST.** There are
  currently no lists, emphasis, tables, images or code blocks, and headings are
  whatever `HEADING_RE` matches. The downstream contract is already a clean
  block list of `('para', [segments])`, so a proper parser can feed the existing
  renderer without disturbing layout. This is the largest capability unlock
  available.
- **Close the glyph gaps.** Handwriting coverage is exactly the characters on
  the templates; `#` and the em dash are still missing. The audit reports every
  fallback with its codepoint and context, which tells you which template boxes
  to add.

### D. Distribution

- **Make it installable.** There is no `pyproject.toml`, so the project cannot
  be pip-installed; the only route in is cloning. A package with a console entry
  point turns this from a repository into a tool.
- **Drop two system dependencies.** Poppler is needed only to rasterize PDF
  paper, and `extract_glyphs.py` already falls back to PyMuPDF when `pdftoppm`
  is absent — applying the same fallback in `paper.py` removes it. The portable
  potracer backend likewise removes the FontForge and `python3.12` pin; it
  should be the default rather than the fallback.
- **A service, afterwards.** The core is already an HTML-to-PDF pipeline, which
  maps onto a request handler plus a pool of warm browsers. It needs the browser
  reuse above first, or every request pays cold start. `--seed` determinism
  gives a free response cache key.

### E. Foundations that have to hold first

- **Get the handwriting suite into CI.** `tests/browser_handwriting.py` is the
  deepest test in the project — real Chromium font selection through CDP,
  semantic MathML preservation, bracket pen-weight consistency, seed
  determinism. CI never runs it, because it needs personal font files that are
  correctly gitignored. Checking in a small synthetic test font makes it run
  everywhere. Until then, changes on every axis above are unguarded in exactly
  the area that makes this project distinctive.
- **Extract the embedded JavaScript.** Around 100 lines of delimiter handling
  live inside the Python f-string, needing doubled braces and quadruple-escaped
  regex backslashes. Moving it to its own file also resolves the implicit-global
  tangle above.
- **Decouple the font logic from Tkinter.** `tests/test_app_fonts.py` fails to
  import on any machine without Tk, because `app.py` imports tkinter at module
  level while the logic under test is pure path handling. `available_styles()`
  and `personal_font_options()` belong in a GUI-free module.

## Open defect

The generated ruled paper has the correct line pitch but the wrong phase.
Measured against the rule grid in the output PDF, every prose baseline sits a
constant ~11pt above the nearest rule instead of resting on it:

```
rules     at y = 0, 30, 60, 90, 120 ... pt   (exactly 30pt, correct)
baselines at 108.9, 137.6, 168.1, 199.4, 229.1, 258.3 pt
offset from nearest rule: 11.1, 12.4, 11.9, 10.6, 10.9, 11.7 pt
```

`paper_layout()` already computes this correction for user-supplied paper
(`pad_top = first_line - baseline_in_box`, from half-leading plus ascent); the
generated-paper path never applies it, and `.page` padding-top carries no
baseline term. It is the highest-visibility fix in the codebase for its size.
