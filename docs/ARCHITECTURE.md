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
| `handwriting/handwrite.py` | 661 | `render(spec)`, font embedding, paper geometry, the HTML document template, Playwright driving. |
| `handwriting/spec.py` | 134 | The render spec: what an output is, how it resolves a hand to fonts and metrics, and how it is saved and reloaded. |
| `handwriting/clean.py` | 296 | Messy-paste repair, block parsing, inline segmentation, safe equation splitting. Pure functions, no I/O. |
| `handwriting/handwriting.js` | 269 | Per-glyph font selection from coverage sets; redraws brackets, vector arrows and radicals as SVG; writes the handwriting audit. |
| `handwriting/app.py` | 168 | Tkinter editor. Renders on a worker thread, polls a queue, surfaces cleanup notes as a warning dialog. |
| `handwriting/layout.js` | 188 | Equation line-splitting, word-atom line breaking, pagination with widow control, the layout report. |
| `handwriting/delimiters.js` | 142 | Swaps KaTeX's stretchy delimiters for handwritten glyphs, and the canvas ink measurement that positions them. |
| `handwriting/random.js` | 9 | The one seeded generator every layer draws from, so a `--seed` reproduces a render exactly. |
| `handwriting/paper.py` | 182 | Read a supplied page (PDF via PyMuPDF or Poppler, or an image), find its rules and margin by pixel coverage. |
| `handwriting/papers.py` | 225 | Paper presets, drawn from their measurements so the geometry is known rather than detected, plus importing pages of your own. |
| `handwriting/hands.py` | 177 | Handwriting profile discovery: bundled fonts and your own hand directories, and the flags each needs. GUI-free so it stays testable headless. |
| `custom_font/` | ~630 | Charset definitions, template generators, glyph extraction, two font-building backends, stroke-profile calibration. |
| `tests/` | ~700 | Unit modules, two browser suites, a synthetic-hand fixture generator, one visual-acceptance PDF generator. |

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

## Why display-math spacing is padding, not margin

Adjacent vertical margins collapse to the larger of the two rather than adding.
Display-math blocks are padded out to a whole number of ruled lines so the prose
after them lands back on a line — arithmetic that only holds if the measured
height is also the flow advance. With margins it was not: three equations in a
row each advanced the page 10px less than believed, and everything below them
sat off the rules. Padding does not collapse, so the space is padding.

`tests/browser_layout.py` asserts every line and equation starts a whole number
of rules below its page's padding box.

## Paper, preset or your own

A preset is a description — rule spacing in millimetres, where the first rule
sits, whether there is a margin — and the page is drawn from it. Its geometry is
therefore exact, rather than measured back out of a rasterised image, and no
page pictures live in the repository. Your own pages go the other way: the rules
are detected once on import and cached beside the page, so by the time anything
renders, a preset and an imported page are the same thing. `papers.load()` is
the single door for all three inputs — preset name, imported name, file path.

One consequence worth keeping: real rule spacings are not whole numbers of CSS
pixels (college ruled is 26.83), so the line height must stay fractional. It
used to be rounded, which walked the writing off the rules across a page and
compounded through display-math padding.

## Installed shape

The runtime is the `handwriting/` package; `custom_font/` (font building) and
`tests/` sit beside it and are not installed. `pyproject.toml` ships the fonts,
KaTeX and the `.js` files as package data, because the renderer reads them from
disk at run time. Three console scripts come with it: `handwrite`,
`handwrite-papers`, `handwrite-app`.

Being importable from anywhere is why the module names matter: `spec`, `clean`
and `paper` are far too generic to sit at the top level of site-packages.
Without `--keep-html` the intermediate document goes to a temp directory rather
than beside the code, which an installed copy has no business writing into.

## A render is a function of a spec

`render(spec, output)` is the whole entry point. A `RenderSpec` holds
everything that decides what the page looks like — content, hand, paper, seed,
and the layout knobs — and nothing about where artefacts go. The CLI parses
options into a spec and calls `render`; `--spec` renders a saved one and
`--save-spec` writes the one the options describe.

That matters beyond tidiness. A render becomes something you can store, diff,
and reproduce, which is the precondition for editing one parameter at a time in
response to "page 4 is too cramped" rather than reconstructing a command line.

Resolution order is worth knowing: explicit `fonts` beat the named hand's own
files, and an explicit `font_size` or `line_height` beats what that hand
recommends in its `hand.json`, which in turn beats the global default. Font
variants are keyed by letter rather than positional, so a hand with A and C but
no B cannot slide C into B's slot.

## How the JavaScript is assembled

Every `.js` file is read from disk and concatenated into one `<script>` block,
in dependency order: `random.js`, `delimiters.js`, `layout.js`,
`handwriting.js`. Python interpolates **only** configuration objects —
`layoutConfig`, `handwritingConfig`, `delimiterConfig` — followed by the call
sequence that runs a render. No JavaScript logic lives in the f-string, so none
of it needs doubled braces or escaped regex backslashes.

The files still share a runtime: `handwriting.js` calls `origInk()` and
`delimsFromTex()` from `delimiters.js`, and writes its audit into
`layoutReport`, which `layout.js` owns. That is deliberate — they compose one
render — but the load order is now explicit rather than resting on function
hoisting, and each file can be read on its own.

## Scaling

Nothing here is architecturally wrong, but nearly every path assumes *one user
rendering one document interactively*. That shows up as process startup per
render, repeated work that could be cached, and a layout loop with a much worse
constant factor than it needs.

### A. Make one render fast — mostly not worth it, once measured

Where a render actually spends its time, on `example_input.txt`:

| | |
|---|---|
| `page.pdf()` | 0.83s |
| Python imports, per process | ~1.0s |
| Playwright + Chromium startup | 0.46s |
| in-page: fonts, KaTeX, layout, pagination | 0.18s |
| `build_html()`, fonts base64 and coverage | 0.02s |

Two items that looked worthwhile in the first analysis were not:

- ~~**Stop re-encoding fonts every render.**~~ 0.02s. Encoding a 430 KB TTF to
  base64 is quick, and caching it would add invalidation logic to buy nothing.
- ~~**Fix the layout thrash.**~~ The per-word `getBoundingClientRect()` loop was
  described as "the real ceiling". Everything in the page — fonts, KaTeX,
  line-breaking, pagination — comes to 0.18s together.

The one real cost is `page.pdf()`, which is Chromium's own print pipeline. The
SVG wobble filter forcing every equation to rasterise is the part of that which
belongs to this project.

- ~~**Keep the browser alive.**~~ Done, as `Renderer`. It changes nothing for a
  single `handwrite` invocation (1.99s to 1.91s, which is just a fixed 150 ms
  sleep that `window.__renderDone` already made redundant). What it changes is
  repeated rendering in one process: 0.46s of startup once, then about 1.18s per
  render instead of a fresh ~1.9s process each time. That is infrastructure for
  editing a render in response to a complaint, not a speed-up of today's CLI.

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
- ~~**Drop two system dependencies.**~~ Done — `paper.py` reads a supplied PDF
  with PyMuPDF (preferring it over Poppler, so rule detection uses the same
  rasterizer everywhere), and `build_font.py` defaults to the pure-pip potracer
  backend with FontForge as an opt-in. Neither is required; a missing reader
  now says what to install rather than raising.
- **A service, afterwards.** The core is already an HTML-to-PDF pipeline, which
  maps onto a request handler plus a pool of warm browsers. It needs the browser
  reuse above first, or every request pays cold start. `--seed` determinism
  gives a free response cache key.

### E. Foundations that have to hold first

- ~~**Get the handwriting suite into CI.**~~ Done — `tests/synthetic_hand.py`
  builds a deterministic four-variant stand-in (plain geometry, not
  handwriting) carrying the characters and sample geometry the suite needs, so
  `tests/browser_handwriting.py` now runs everywhere, including CI. Real
  personal fonts are still preferred when present.
- **Extract the embedded JavaScript.** Around 100 lines of delimiter handling
  live inside the Python f-string, needing doubled braces and quadruple-escaped
  regex backslashes. Moving it to its own file also resolves the implicit-global
  tangle above.
- ~~**Decouple the font logic from Tkinter.**~~ Done — `available_styles()` and
  `personal_font_options()` now live in `hands.py`, which imports no GUI
  toolkit, and the test suite runs on a machine without Tk.

## Sitting on the rules

Writing has to rest *on* a ruled line, not merely repeat at its pitch — pitch
without phase is what makes output read as a font on a grid rather than as
handwriting.

Both paper paths now carry the correction. For a supplied page,
`paper_layout()` derives it from the detected first rule
(`pad_top = first_line - baseline_in_box`). For the generated paper,
`first_rule_offset()` derives it from the font's own vertical metrics and the
rule spacing: the background paints its rule in the last pixel of each
line-height band, so rule centres sit half a pixel above each multiple of the
spacing, and the padding is whatever shifts the first baseline onto one.

Both are computed from metrics, never tuned by eye — a hardcoded offset is
wrong the moment the font or the size changes. `tests/test_ruled_paper.py`
asserts the invariant across every bundled font at four size/leading pairs.

Residual deviation in a rendered PDF is the deliberate per-line jitter
(a translate of up to ±1.5px plus a small rotation), so baselines scatter
within roughly 2.5pt of the rules rather than landing exactly. That scatter is
centred on zero; a systematic offset is the bug.
