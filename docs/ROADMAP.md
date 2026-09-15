# Roadmap

Where the project is going, and the order to get there. Sprints 1 to 4 are
done; 5 to 7 are still design. For how the current system works, see
[ARCHITECTURE.md](ARCHITECTURE.md).

## The product, as one flow

You give it three things: **content** (a text file or a PDF), **paper** (a
preset, or a page you exported yourself), and a **hand** (yours, or one of
several you have imported). It returns a handwritten PDF. Then you say
*"page 4 is cramped and the third equation runs off the edge"*, and it fixes
that and re-renders. Optionally you ask for the paper to look folded and a
little dirty, so it reads as something that actually existed.

That sentence contains five capabilities the project does not have yet.

## What exists versus what that needs

| Capability | State | What is missing |
|---|---|---|
| Text in, handwriting out | Have | Nothing. This is the working core. |
| Your own handwriting | **Have** | A hand is a directory under `~/.handwriting/hands/`; keep as many as you like. |
| Your own paper | **Have** | Six presets, or import a page of your own and use it by name. |
| PDF as input | New | Everything. Text-layer extraction is easy; scanned pages need OCR; math needs a vision model. |
| Aged / folded / dirty paper | New | Everything. A finishing pass compositing over the rendered page. |
| "Fix page 4" | New | The AI loop. The spec it edits and the `Renderer` it re-runs both exist now. |

## The idea everything hangs on: a render spec

A render is currently defined by eighteen command-line flags. Nothing can
inspect, store, diff, or change it. Introduce a **render spec**: one JSON
document that fully describes an output.

```json
{
  "version": 1,
  "content":   { "source": "notes.pdf", "adapter": "pdf-text",
                 "extracted": "notes.extracted.md" },
  "paper":     { "preset": "ruled-narrow" },
  "hand":      { "profile": "bigyan", "variants": ["A", "B", "C", "D"] },
  "layout":    { "font_size": 30, "line_height": 44, "hand_math": true },
  "finishing": { "fold": null, "stain": null, "grain": null },
  "seed": 7,
  "overrides": [ { "scope": {"page": 4}, "set": {"font_size": 28} } ]
}
```

Rendering becomes `render(spec) -> (pdf, report)`: deterministic, no hidden
inputs. That single move pays for itself five times:

- The CLI builds a spec and renders it; the desktop app edits a spec. One code
  path instead of two that drift.
- Revisions are diffs. Keeping old specs gives version history for free.
- The AI loop has something safe to edit — a validated JSON document, never
  code and never the PDF.
- `overrides` with a scope is what makes "page 4" expressible at all. Without
  it there is no way to say "smaller, but only there".
- Reproducibility survives: a spec plus a hand reproduces an exact output.

## The five new subsystems

### Hands — a profile, not a hardcoded name

A hand is a folder. Bundled fonts become profiles of the same shape, which
collapses today's two code paths (`--font` versus `--custom-font`) into one.

```
~/.handwriting/hands/bigyan/
    hand.json          name, recommended font_size + line_height, coverage
    A.ttf B.ttf C.ttf D.ttf
    A.handwriting.json ...   bracket centrelines, arrow geometry, pen weight
```

`hand.json` carries the numbers `app.py` currently hardcodes. With
`handwrite hands list` and `hands import`, several handwritings cost nothing
extra — each is another folder.

### Papers — a small library plus your own

Ship presets as image plus precomputed geometry, so rendering never pays
detection cost: ruled narrow, ruled wide, college, graph 5 mm, dotted, blank.
Importing your own page runs today's detector once and caches the result.

**Prerequisite:** the baseline phase defect must be fixed first. Presets are
worthless if text floats ~11pt above every rule — that would just be six
papers that are all subtly wrong.

### Input adapters — one job, several implementations

An adapter turns a source into the block list the parser already produces.
Stage them by reliability:

- `text` / `markdown` — the existing path, plus a real Markdown parser for
  lists, tables and emphasis.
- `pdf-text` — PDFs carrying a text layer. Straightforward, and the common case.
- `pdf-scan` — image-only pages. Needs OCR.
- `pdf-math` — typeset equations back into LaTeX. Genuinely hard; a vision
  model, and explicitly best-effort.

Carry over the pattern the project already uses for messy pastes: **extract,
show a reviewable intermediate, then render.** Import writes an
`.extracted.md` you can correct before anything is drawn, rather than silently
producing a wrong page.

### Finishing — folds, stains, wear

A post-render pass, opt-in and off by default, because compositing rasterizes
the page and loses selectable text. Effects are named, parameterised, and
deterministic under the spec's seed like everything else.

```json
"finishing": { "fold": {"style": "thirds", "strength": 0.4},
               "stain": {"count": 2, "opacity": 0.15},
               "edge_wear": 0.3, "grain": 0.2, "skew": 0.4 }
```

Pillow and NumPy are already dependencies, so this needs nothing new: a soft
shadow band and slight warp for a fold, procedural multiply-blended blobs for
stains, noise for grain, alpha erosion at the borders, a fractional rotation
for scanner skew.

### Revision — the loop that makes it feel like a tool

This looks hardest and is actually cheapest, because the renderer already
emits a structured self-audit. `--analyze` reports page fill against capacity,
words per line, overwide equations *with the offending LaTeX*, and every glyph
that fell back — almost exactly the vocabulary of complaints a person has
about a page.

The loop assembles the current spec, the layout report, a PNG of the named
page, and a schema of what may legally change. The model returns a patch —
never prose, never code:

```json
{ "diagnosis": "Page 4 is at 96% of capacity; the report flags
                \\begin{bmatrix}... at 812px in a 780px column.",
  "changes": [
    {"scope": {"page": 4},       "param": "font_size", "from": 30, "to": 28},
    {"scope": {"equation": "..."}, "param": "split",   "to": "force"} ],
  "confidence": "high",
  "unaddressed": [] }
```

Apply, re-render, show before and after, accept or reject. Three properties
make this safe rather than magic: the model cannot act outside the schema
(anything unrecognised is rejected before the renderer sees it); every patch
is reversible, because the previous spec is still on disk; and the mapping
from complaint to patch is unit-testable without rendering anything.

Use `claude-opus-5` with structured outputs, so the response is schema-valid
by construction rather than by parsing and hoping. Cache the stable half of
the prompt — system text plus parameter schema — and each revision costs a
fraction of a cent, since the variable part is one page image and one report.

**This is why speed is a feature, not an optimisation.** A revision is a
re-render, and a fresh process per render costs about 1.9s of which most is
getting ready rather than working. `Renderer` (Sprint 4) holds one browser open
so a revision costs about 1.18s of actual rendering.

## Sprints

Each sprint ends with something that works, not a half-migration.

### Sprint 1 — Analysis (complete)

Full source read, test suite run, end-to-end render, PDF-level measurement.
Shipped as [ARCHITECTURE.md](ARCHITECTURE.md).

### Sprint 2 — Foundation: safe to change

You cannot refactor confidently while the most distinctive part of the project
has no automated coverage. This sprint builds the net.

- Check in a synthetic test font so the handwriting suite runs in CI
- Fix the ruled-paper baseline phase (~11pt offset)
- Extract the embedded delimiter JavaScript into its own file
- Move font-selection logic out of the Tkinter module

### Sprint 3 — Keystone: any hand, any paper

Introduce the render spec and the two profile systems. After this sprint the
hardcoded `BigyanHand` is gone and the tool is installable.
*Depends on Sprint 2 — the paper work is pointless before the phase fix.*

- Introduce the render spec; make rendering a pure function of it
- Handwriting profile system, replacing the hardcoded personal font
- Paper preset library, plus import for your own pages
- Packaging and a console entry point
- Drop the Poppler and FontForge hard dependencies

### Sprint 4 — Speed: fast enough to iterate

Measured before optimising, which cut the sprint down to one item.

- Keep one browser alive across renders — **done** (`Renderer`). Repeated
  rendering in one process goes from ~1.9s per render to 0.46s once plus ~1.18s
  each.
- ~~Cache font encoding and coverage~~ — 0.02s. Not worth the invalidation
  logic.
- ~~Batch layout measurement~~ — the whole in-page phase is 0.18s, so the
  per-word reflow loop called "the real ceiling" in the first analysis is a
  fraction of a fraction.

The dominant per-render cost is `page.pdf()` at 0.83s, inside Chromium's print
pipeline. The part of that which is ours is the SVG wobble filter, which forces
every equation to rasterise; changing it is a visual decision, not a tuning one.

### Sprint 5 — Input: accepts what you actually have

*Depends on Sprint 3 — adapters are selected by the spec.*

- Replace the line-based parser with a real Markdown AST
- PDF text-layer adapter with a reviewable extracted intermediate
- Add the missing handwriting characters (`#`, em dash)

### Sprint 6 — Realism: looks like it existed

Independent of everything else, so it can move earlier for a visible win.

- Finishing-pass framework, seeded and opt-in
- Fold, stain, edge wear, grain and scan-skew effects

### Sprint 7 — The loop: "fix page 4"

The headline feature, deliberately last.
*Depends on Sprints 3 and 4. Do not start early.*

- Define the RenderPatch schema and validator
- Page-context assembly: spec, report and page image
- Claude integration via structured outputs
- Revision history with accept and reject

### Backlog — not on the critical path

- Chunked rendering for very long documents
- Derive words-per-line from measured column width
- OCR adapter for scanned pages
- Vision-model transcription of typeset math

## Working process

Three objects, all free in GitHub:

- **Issue** — one problem. Not a theme, not a sprint. If it cannot be closed
  by one pull request, split it.
- **Milestone** — one sprint, e.g. `Sprint 2 — Foundation`.
- **Label** — how you slice across milestones: `type:bug` / `type:feature` /
  `type:chore`, and `size:s` / `m` / `l`.

The design lives in this repository; the work lives in issues. Each issue
states Problem, Why it matters, Proposed solution, Done when, and Depends on.
"Done when" is the part that matters — write it before starting, while you
still remember what you wanted.

One issue, one branch, one pull request. Small pull requests get reviewed;
large ones get skimmed.

A sprint is a checkpoint, not a deadline. Stop at the end, look at what you
learned, and re-plan — Sprint 3 will probably teach you the spec's shape is
slightly wrong, and that is better found before Sprint 7 depends on it.

**The ordering that matters:** Sprint 2 before everything, because it is the
safety net. Sprints 3 and 4 before 7, because the loop is built on them.
Sprint 6 can float. Everything else is negotiable.
