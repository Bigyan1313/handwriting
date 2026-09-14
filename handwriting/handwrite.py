#!/usr/bin/env python3
"""
handwrite.py -- turn a typed-up math solution into a natural-looking
"handwritten" PDF (ruled paper, handwriting font, subtle per-word jitter,
real typeset math via KaTeX with a light hand-drawn wobble).

Usage:
    python3 handwrite.py input.txt output.pdf
    python3 handwrite.py input.txt output.pdf --font kalam --seed 3
    python3 handwrite.py input.txt output.pdf --clean   # skip messy-paste cleanup

Fonts available (see fonts/): kalam (default), indieflower, patrickhand,
caveat, reeniebeanie, shadowsintolight, gochihand.
"""
import argparse
import base64
import html
import io
import json
import random
import sys
import tempfile
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

from handwriting import clean as cleaner
from handwriting import paper as paperlib
from handwriting import papers as paperslib
from handwriting.spec import DEFAULT_FONT_SIZE, RenderSpec

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "fonts"
KATEX_DIR = HERE / "assets" / "katex"

FONTS = {
    "kalam": {
        "family": "HandwritingFont",
        "regular": "Kalam-Regular.ttf",
        "bold": "Kalam-Bold.ttf",
    },
    "indieflower": {"family": "HandwritingFont", "regular": "IndieFlower-Regular.ttf"},
    "patrickhand": {"family": "HandwritingFont", "regular": "PatrickHand-Regular.ttf"},
    "caveat": {"family": "HandwritingFont", "regular": "Caveat-Variable.ttf"},
    "reeniebeanie": {"family": "HandwritingFont", "regular": "ReenieBeanie-Regular.ttf"},
    "shadowsintolight": {"family": "HandwritingFont", "regular": "ShadowsIntoLight-Regular.ttf"},
    "gochihand": {"family": "HandwritingFont", "regular": "GochiHand-Regular.ttf"},
}


def font_vmetrics(path: str):
    """(ascent, descent, unitsPerEm) for a font file, used to land the first
    line's baseline exactly on the paper's first ruled line."""
    from fontTools.ttLib import TTFont
    f = TTFont(path, fontNumber=0)
    upem = f["head"].unitsPerEm
    asc, desc = f["hhea"].ascent, -f["hhea"].descent
    if not asc:
        asc, desc = f["OS/2"].sTypoAscender, -f["OS/2"].sTypoDescender
    return asc, desc, upem


def paper_layout(paper_ref: str, font_path: str, font_size: int):
    """Work out the CSS geometry needed to write onto a ruled page:
    page size, line-height matching the rules, and the top/left padding that
    puts the first baseline on the first rule and clears the margin rule.

    `paper_ref` is a preset name, one of your imported pages, or a file path;
    papers.load() hands all three back in the same form.
    """
    img, rules = paperslib.load(paper_ref)
    path = Path(paper_ref)

    page_w_in, page_h_in = 8.5, 11.0
    if path.suffix.lower() == ".pdf" and path.is_file():
        size = paperlib.page_size_in(path)
        if size:
            page_w_in, page_h_in = size
    else:
        w, h = img.size
        page_h_in = page_w_in * h / w

    px_per_in = 96.0  # CSS px
    page_w_css, page_h_css = page_w_in * px_per_in, page_h_in * px_per_in

    if not rules["line_spacing_frac"]:
        return None, rules

    line_height = rules["line_spacing_frac"] * page_h_css
    first_line = rules["first_line_frac"] * page_h_css

    asc, desc, upem = font_vmetrics(font_path)
    content_h = font_size * (asc + desc) / upem
    half_leading = (line_height - content_h) / 2.0
    baseline_in_box = half_leading + font_size * asc / upem
    pad_top = first_line - baseline_in_box

    if rules["margin_x_frac"] is not None:
        pad_left = rules["margin_x_frac"] * page_w_css + 14
    else:
        pad_left = 0.09 * page_w_css

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    bg_b64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "page_w_in": page_w_in, "page_h_in": page_h_in,
        "line_height": line_height, "pad_top": max(pad_top, 0),
        "pad_left": pad_left, "bg_b64": bg_b64,
    }, rules


def first_rule_offset(font_path, font_size: int, line_height: int) -> float:
    """Top padding that lands the first baseline on a rule of the *generated*
    ruled paper.

    The generated background paints its rule in the last pixel of each
    line-height band, so rule centres sit half a pixel above each multiple of
    the spacing. Without this the writing keeps the right pitch but sits at the
    wrong phase, floating a constant distance above every rule. It is the same
    correction paper_layout() already makes for a supplied page.
    """
    asc, desc, upem = font_vmetrics(str(font_path))
    content_h = font_size * (asc + desc) / upem
    baseline_in_box = (line_height - content_h) / 2.0 + font_size * asc / upem
    return (line_height - 0.5 - baseline_in_box) % line_height


def _face(family: str, path: str) -> str:
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    return f"""
@font-face {{
  font-family: '{family}';
  src: url(data:font/ttf;base64,{b64}) format('truetype');
  font-weight: 400 700;
}}"""


def font_face_css(font_key: str, custom_font_path: str = None,
                  custom_font_b_path: str = None, custom_font_c_path: str = None,
                  custom_font_d_path: str = None) -> str:
    if custom_font_path:
        css = _face("HandwritingFont", custom_font_path)
        if custom_font_b_path:
            css += _face("HandwritingFontB", custom_font_b_path)
        for suffix, path in [('C', custom_font_c_path), ('D', custom_font_d_path)]:
            if path:
                css += _face('HandwritingFont' + suffix, path)
        return css
    spec = FONTS[font_key]
    family = spec["family"]
    parts = []
    reg_path = FONT_DIR / spec["regular"]
    reg_b64 = base64.b64encode(reg_path.read_bytes()).decode()
    parts.append(f"""
@font-face {{
  font-family: '{family}';
  src: url(data:font/ttf;base64,{reg_b64}) format('truetype');
  font-weight: 400;
}}""")
    if "bold" in spec:
        bold_path = FONT_DIR / spec["bold"]
        bold_b64 = base64.b64encode(bold_path.read_bytes()).decode()
        parts.append(f"""
@font-face {{
  font-family: '{family}';
  src: url(data:font/ttf;base64,{bold_b64}) format('truetype');
  font-weight: 700;
}}""")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Jitter: wrap each word in a span with a small deterministic random
# rotation / vertical offset / ink-tone variation so it doesn't read as a
# uniform digital font block.
# ---------------------------------------------------------------------------

def vary_chars(word: str, rng: random.Random, two_variants: bool) -> str:
    """With a second handwriting variant available, randomly pick which
    version of each letter to use, so repeated letters in a word aren't
    identical stamps of each other."""
    families = two_variants if isinstance(two_variants, list) else (['', 'B'] if two_variants else [''])
    return ''.join(f'<span style="font-family:HandwritingFont{rng.choice(families)},HandwritingFont">{html.escape(ch)}</span>' for ch in word) if len(families) > 1 else html.escape(word)


def jitter_text(text: str, rng: random.Random, jitter: bool,
                two_variants: bool = False) -> str:
    if not text:
        return ""
    out = []
    # keep leading/trailing whitespace of the segment intact
    for tok in re_split_keep_spaces(text):
        if tok.strip() == "":
            out.append(html.escape(tok))
            continue
        inner = vary_chars(tok, rng, two_variants)
        if not jitter:
            out.append(f'<span class="w">{inner}</span>')
            continue
        rot = rng.uniform(-0.7, 0.7)
        dy = rng.uniform(-0.7, 0.7)
        dark = rng.uniform(0.78, 1.0)
        out.append(
            f'<span class="w" style="display:inline-block;'
            f'transform:rotate({rot:.2f}deg) translateY({dy:.2f}px);'
            f'opacity:{dark:.2f}">{inner}</span>'
        )
    return "".join(out)


import re as _re


def re_split_keep_spaces(text: str):
    return _re.findall(r'\S+|\s+', text)


# ---------------------------------------------------------------------------
# HTML building
# ---------------------------------------------------------------------------

def render_segments(segments, rng, jitter, two_variants=False):
    out = []
    for seg in segments:
        if seg[0] == "text":
            out.append(jitter_text(seg[1], rng, jitter, two_variants))
        elif seg[0] == "label":
            out.append(f'<span class="label">{jitter_text(seg[1], rng, jitter, two_variants)}</span>')
        else:  # math
            latex = html.escape(seg[1], quote=True)
            out.append(f'<span class="math-src" data-tex="{latex}"></span>')
    return "".join(out)


HAND_MATH_CSS = """
.katex {{ font-size: {math_scale}em !important; }}
.hand-glyph {{ font-style: normal !important; }}
.hand-bracket, .hand-vector-arrow {{ overflow: visible; pointer-events: none; }}
"""


def font_resources(font_key, paths):
    """Embed coverage and optional sample geometry so saved HTML is self-contained."""
    from fontTools.ttLib import TTFont
    resources = {}
    available = [(suffix, path) for suffix, path in paths if path]
    if not available:
        available = [('', FONT_DIR / FONTS[font_key]['regular'])]
    for suffix, path in available:
        path = Path(path)
        with TTFont(path) as font:
            coverage = ''.join(chr(code) for code in sorted(font.getBestCmap()))
            radical = None
            glyph_name = font.getBestCmap().get(ord('√'))
            if glyph_name:
                from fontTools.pens.boundsPen import BoundsPen
                from fontTools.pens.svgPathPen import SVGPathPen
                glyphs = font.getGlyphSet()
                bounds = BoundsPen(glyphs)
                outline = SVGPathPen(glyphs)
                glyphs[glyph_name].draw(bounds)
                glyphs[glyph_name].draw(outline)
                if bounds.bounds:
                    radical = {'path': outline.getCommands(), 'bounds': bounds.bounds}
        profile_path = path.with_suffix('.handwriting.json')
        profile = json.loads(profile_path.read_text()) if profile_path.exists() else None
        resources['HandwritingFont' + suffix] = {'coverage': coverage, 'profile': profile,
                                               'radical': radical}
    return resources


def build_html(blocks, font_key: str, seed: int, jitter: bool, custom_font_path: str = None,
               font_size: int = 22, line_height: int = 40, hand_math: bool = False,
               math_scale: float = 1.28, custom_font_b_path: str = None,
               paper: dict = None, hand_delims: bool = True,
               custom_font_c_path: str = None, custom_font_d_path: str = None,
               bracket_stroke_scale: float = 1.0) -> str:
    if not 0 < bracket_stroke_scale < float('inf'):
        raise ValueError('bracket_stroke_scale must be a finite positive number')
    resources = font_resources(font_key, [('', custom_font_path), ('B', custom_font_b_path),
                                        ('C', custom_font_c_path), ('D', custom_font_d_path)])
    rng = random.Random(seed)
    two_variants = [''] + [suffix for suffix, path in [('B', custom_font_b_path), ('C', custom_font_c_path), ('D', custom_font_d_path)] if path] if custom_font_path else ['']
    body_parts = []
    groups = blocks if blocks and blocks[0][0] == 'problem_group' else cleaner.group_problems(blocks)
    for index, (_, children) in enumerate(groups):
        body_parts.append(f'<div class="problem-block" data-problem="{index + 1}">')
        for block in children:
            if block[0] == 'para':
                body_parts.append(f'<div class="para">{render_segments(block[1], rng, jitter, False)}</div>')
            elif block[0] == 'display_math':
                latex = html.escape(block[1], quote=True)
                parts = html.escape(json.dumps(cleaner.equation_parts(block[1])), quote=True)
                body_parts.append(f'<div class="display-math-src" data-tex="{latex}" data-parts="{parts}"></div>')
        body_parts.append('</div>')
    body_html = "\n".join(body_parts)

    face_css = font_face_css(font_key, custom_font_path, custom_font_b_path, custom_font_c_path, custom_font_d_path)
    family = "HandwritingFont" if custom_font_path else FONTS[font_key]["family"]

    # Handwritten stretchy delimiters need a custom font to take glyphs from,
    # and the font's own vertical metrics to place them.
    hand_delims_on = False
    font_asc, font_upem = 800, 1000
    if custom_font_path:
        try:
            font_asc, _, font_upem = font_vmetrics(custom_font_path)
            if hand_math and hand_delims:
                hand_delims_on = True
        except Exception:
            pass

    if paper:
        # Keep the rule spacing exact. Rounding to a whole pixel drifts the
        # writing off the rules over a page, and display-math padding snaps
        # to multiples of it, which compounds the error fast.
        line_height = paper["line_height"]
        page_css = (f'@page {{ size: {paper["page_w_in"]:.3f}in {paper["page_h_in"]:.3f}in; '
                    f'margin: 0; }}')
        body_bg_css = (
            f'  background-image: url(data:image/png;base64,{paper["bg_b64"]});\n'
            f'  background-size: 100% auto;\n'
            f'  background-repeat: repeat-y;\n'
            f'  padding: {paper["pad_top"]:.1f}px 48px 40px {paper["pad_left"]:.1f}px;\n'
        )
    else:
        page_css = "@page { size: Letter; margin: 0; }"
        body_bg_css = None

    page_width = paper['page_w_in'] * 96 if paper else 816
    page_height = paper['page_h_in'] * 96 if paper else 1056
    if paper:
        base_top = paper['pad_top']
    else:
        base_top = first_rule_offset(
            custom_font_path or FONT_DIR / FONTS[font_key]['regular'],
            font_size, line_height)
    body_paint = body_bg_css if body_bg_css else """  padding: var(--top-pad) 110px 60px calc(var(--margin-col) + 28px);
  background-color: #fbf9f2;
  background-image:
    linear-gradient(to right, transparent 0, transparent var(--margin-col),
                     rgba(214, 84, 84, 0.55) var(--margin-col),
                     rgba(214, 84, 84, 0.55) calc(var(--margin-col) + 2px),
                     transparent calc(var(--margin-col) + 2px)),
    repeating-linear-gradient(
      to bottom,
      transparent 0,
      transparent calc(var(--line-height) - 1px),
      rgba(120, 150, 200, 0.55) calc(var(--line-height) - 1px),
      rgba(120, 150, 200, 0.55) var(--line-height)
    );
  background-position: 0 0, 0 0;
  background-repeat: repeat, repeat;"""
    hand_math_css = ""
    if hand_math:
        hand_math_css = HAND_MATH_CSS.format(
            family=family, math_scale=f"{math_scale:.3f}",
            math_unscale=f"{1.0 / math_scale:.3f}",
        )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="{KATEX_DIR / 'katex.min.css'}">
<style>
{face_css}

:root {{
  --line-height: {line_height}px;
  --top-pad: 90px;
  --margin-col: 76px;
}}

* {{ box-sizing: border-box; }}

html, body {{
  margin: 0;
  padding: 0;
  background: #f7f4ec;
}}

body {{
  font-family: '{family}', cursive;
  font-size: {font_size}px;
  line-height: var(--line-height);
  color: #1a2e6b;
}}
.page, #source {{
  width: {page_width}px;
{body_paint}
  padding-right: 110px;
}}
.page {{ height: {page_height}px; break-after: page; display: flow-root; }}
.page:last-child {{ break-after: auto; }}
#source {{ position:absolute; left:-20000px; top:0; }}
.problem-block {{ display: flow-root; }}
.hand-line {{ white-space: nowrap; min-height: var(--line-height); transform-origin: left center; }}
.w, .math-src {{ display: inline-block; }}
.katex-display {{ margin: 0; text-align: left; }}
.katex-display > .katex {{ text-align: left; }}
.katex-display .katex-html {{ display: inline-block !important; width: max-content; }}


.label {{
  font-weight: 700;
}}

.para {{ margin: 0; }}
.para + .para {{ margin-top: 2px; }}

.display-math-src {{
  display: block;
  /* Vertical space as padding, not margin: adjacent margins collapse, which
     would make a run of equations advance the page by less than its height. */
  margin: 0 0 0 12px;
  padding: 10px 0 14px;
}}

.math-src, .display-math-src {{
  filter: url(#wobble);
}}

.katex {{ font-size: 1.05em; color: #1a2e6b; }}

{hand_math_css}

{page_css}
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute">
  <filter id="wobble" x="-20%" y="-20%" width="140%" height="140%">
    <feTurbulence type="fractalNoise" baseFrequency="0.015 0.04" numOctaves="2" seed="4" result="noise"/>
    <feDisplacementMap in="SourceGraphic" in2="noise" scale="1.6"/>
  </filter>
</svg>
<div id="source">{body_html}</div>
<script src="{KATEX_DIR / 'katex.min.js'}"></script>
<script>
  window.__renderDone = false;
  document.querySelectorAll('.math-src').forEach(function(el) {{
    try {{
      katex.render(el.dataset.tex, el, {{displayMode: false, throwOnError: false}});
    }} catch (e) {{ el.textContent = el.dataset.tex; }}
  }});
  document.querySelectorAll('.display-math-src').forEach(function(el) {{
    try {{
      katex.render(el.dataset.tex, el, {{displayMode: true, throwOnError: false}});
    }} catch (e) {{ el.textContent = el.dataset.tex; }}
  }});

  // Everything below measures rendered geometry (glyph ink extents, block
  // widths, line positions), so it has to wait until the webfonts are
  // actually loaded -- otherwise canvas metrics fall back to a default face
  // and come out wrong.
  // document.fonts.ready can resolve before the browser has even requested a
  // face it hasn't laid out yet, which makes canvas metrics silently fall back
  // to a default font. Load every family we're about to measure explicitly.
  function withFontsLoaded(cb) {{
    var fams = ['HandwritingFont', 'HandwritingFontB', 'HandwritingFontC', 'HandwritingFontD', 'KaTeX_Main', 'KaTeX_Math'];
    document.querySelectorAll('.katex .delimsizing').forEach(function (el) {{
      var f = getComputedStyle(el).fontFamily.split(',')[0].replace(/["']/g, '').trim();
      if (f && fams.indexOf(f) < 0) fams.push(f);
    }});
    var jobs = fams.map(function (f) {{
      try {{ return document.fonts.load("100px '" + f + "'", '[]{{}}()|x'); }}
      catch (e) {{ return Promise.resolve(); }}
    }});
    Promise.all(jobs).then(function () {{ return document.fonts.ready; }})
      .then(cb).catch(cb);
  }}
  withFontsLoaded(function () {{

  var layoutConfig = {json.dumps({'seed': seed, 'jitter': jitter, 'lineHeight': line_height, 'pageHeight': page_height, 'baseTop': base_top})};
  const handwritingConfig = {json.dumps({'resources': resources, 'seed': seed, 'handMath': hand_math, 'handDelims': bool(custom_font_path and hand_math and hand_delims), 'bracketStrokeScale': bracket_stroke_scale})};
  var delimiterConfig = {json.dumps({'enabled': hand_delims_on, 'variants': ['HandwritingFont' + x for x in two_variants], 'seed': seed, 'fontAscent': font_asc, 'fontUpem': font_upem})};

  {(HERE / 'random.js').read_text()}
  {(HERE / 'delimiters.js').read_text()}
  {(HERE / 'layout.js').read_text()}
  {(HERE / 'handwriting.js').read_text()}

  decorateProse();
  prepareEquations();
  document.querySelectorAll('.math-src, .display-math-src').forEach(root => decorateMath(root));
  applyHandDelimiters();

  padDisplayMathToRules();
  paginate();
  auditHandwriting();
  window.__renderDone = true;
  }});
</script>
</body>
</html>
"""


def render(spec, output, keep_html=None, analyze=False):
    """Render a spec to a PDF. Returns the layout report.

    Everything that decides what the page looks like comes from the spec; the
    arguments here are only about where the artefacts go.
    """
    raw = Path(spec.content).read_text(encoding='utf-8-sig')
    text, notes = (raw, []) if spec.clean else cleaner.clean_messy_text(raw)
    if notes:
        print("Cleanup notes:", file=sys.stderr)
        for n in notes:
            print(("  [!] " if n.startswith("WARNING") else "  - ") + n, file=sys.stderr)

    variants = spec.font_variants()
    custom = variants.get('A')
    font_key = spec.font_key()
    font_size, line_height = spec.metrics()
    font_for_metrics = custom or str(FONT_DIR / FONTS[font_key]["regular"])

    paper = None
    if spec.paper:
        if font_size is None:
            # Size the writing to the paper: aim for an x-height around 40% of
            # the rule spacing, but never let ascender+descender overrun the
            # spacing by more than a little.
            probe, _ = paper_layout(spec.paper, font_for_metrics, 22)
            if probe:
                asc, desc, upem = font_vmetrics(font_for_metrics)
                lh = probe["line_height"]
                font_size = int(round(min(0.40 * lh / 0.341, 1.15 * lh * upem / (asc + desc))))
                print(f"Auto font size for this paper: {font_size}px "
                      f"(rule spacing {lh:.1f}px)", file=sys.stderr)
            else:
                font_size = DEFAULT_FONT_SIZE
        paper, rules = paper_layout(spec.paper, font_for_metrics, font_size)
        print(paperlib.describe(rules), file=sys.stderr)
        if paper is None:
            print("  -> using the generated ruled paper instead.", file=sys.stderr)
    if font_size is None:
        font_size = DEFAULT_FONT_SIZE

    blocks = cleaner.parse_blocks(text, grouped=True)
    html_doc = build_html(blocks, font_key, spec.seed, jitter=spec.jitter,
                          custom_font_path=custom,
                          font_size=font_size, line_height=line_height,
                          hand_math=spec.hand_math, math_scale=spec.math_scale,
                          custom_font_b_path=variants.get('B'), paper=paper,
                          hand_delims=spec.hand_delims,
                          custom_font_c_path=variants.get('C'),
                          custom_font_d_path=variants.get('D'),
                          bracket_stroke_scale=spec.bracket_stroke_scale)

    # Without --keep-html the intermediate goes to a temp directory: an
    # installed package has no business writing inside itself, and site-packages
    # may not even be writable.
    scratch = None
    if keep_html:
        html_path = Path(keep_html)
    else:
        scratch = tempfile.TemporaryDirectory(prefix='handwrite-')
        html_path = Path(scratch.name) / '_render.html'
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_doc)

    if sync_playwright is None:
        sys.exit(
            "Error: Playwright is required to render PDF output.\n"
            "Please install it by running:\n"
            "    pip install playwright"
        )

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=["--no-sandbox"])
        except Exception:
            # Fallback to system Google Chrome if playwright's chromium isn't installed
            browser = p.chromium.launch(args=["--no-sandbox"], channel="chrome")
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri())
        page.wait_for_function("window.__renderDone === true")
        page.wait_for_timeout(150)
        report = page.evaluate('window.__layoutReport')
        if analyze:
            report_path = Path(output).with_suffix('.layout.json')
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2))
        if report['warnings']:
            print('Layout warnings: ' + '; '.join(report['warnings']), file=sys.stderr)
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        page.pdf(path=output, print_background=True, prefer_css_page_size=True)
        browser.close()
    if scratch:
        scratch.cleanup()
    return report


def spec_from_args(args):
    """The spec these command-line options describe."""
    variants = {letter: path for letter, path in
                zip('ABCD', [args.custom_font, args.custom_font_b,
                             args.custom_font_c, args.custom_font_d]) if path}
    return RenderSpec(
        content=args.input, hand=args.hand or args.font, fonts=variants,
        paper=args.paper, font_size=args.font_size, line_height=args.line_height,
        seed=args.seed, jitter=not args.no_jitter, clean=args.clean,
        hand_math=args.hand_math, hand_delims=not args.no_hand_delims,
        math_scale=args.math_scale, bracket_stroke_scale=args.bracket_stroke_scale)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs='?', help="input text/markdown file (with --spec, the output PDF path)")
    ap.add_argument("output", nargs='?', help="output PDF path")
    ap.add_argument("--spec", metavar="PATH", help="render this saved spec instead of the options below")
    ap.add_argument("--save-spec", metavar="PATH", help="write the spec these options describe")
    ap.add_argument("--font", choices=list(FONTS.keys()), default="kalam")
    ap.add_argument("--hand", metavar="NAME", help="one of your own handwriting profiles (see `hands`)")
    ap.add_argument("--custom-font", metavar="PATH", help="use your own .ttf (e.g. one built from your handwriting) instead of --font")
    ap.add_argument("--paper", metavar="NAME|PATH", help="write onto a paper preset, one of your imported pages, or a PDF/image file (see `python3 papers.py list`)")
    ap.add_argument("--list-papers", action="store_true", help="show every paper you can write on, and exit")
    ap.add_argument("--custom-font-b", metavar="PATH", help="second variant of your handwriting; characters alternate between the two")
    ap.add_argument("--font-size", type=int, default=None, help="body text size in px (default 22; custom fonts often want more)")
    ap.add_argument("--hand-math", action="store_true", help="render the math in the handwriting font too (KaTeX still does the layout)")
    ap.add_argument("--no-hand-delims", action="store_true", help="keep KaTeX's brackets instead of your handwritten ones (only relevant with --hand-math)")
    ap.add_argument("--math-scale", type=float, default=1.28, help="size bump for hand-rendered math (default 1.28)")
    ap.add_argument("--line-height", type=int, default=None, help="ruled line spacing in px (default 40)")
    ap.add_argument("--seed", type=int, default=1, help="random seed for jitter (change for a different look)")
    ap.add_argument("--clean", action="store_true", help="input is already clean LaTeX/Markdown -- skip messy-paste cleanup")
    ap.add_argument("--no-jitter", action="store_true", help="disable per-word jitter (uniform font look)")
    ap.add_argument("--keep-html", metavar="PATH", help="also save the intermediate HTML for inspection")
    ap.add_argument('--custom-font-c', metavar='PATH')
    ap.add_argument('--custom-font-d', metavar='PATH')
    ap.add_argument('--bracket-stroke-scale', type=float, default=1.0, help='bracket pen width relative to nearby handwriting (default 1.0)')
    ap.add_argument('--analyze', action='store_true', help='print measured layout report and save JSON beside PDF')
    args = ap.parse_args()

    if args.list_papers:
        for name in paperslib.PRESETS:
            print(f'  {name:<14} {paperslib.PRESETS[name]["display"]}')
        for name in paperslib.imported_names():
            print(f'  {name:<14} yours')
        return

    if args.spec:
        if args.output:
            ap.error('with --spec, give only the output path')
        if not args.input:
            ap.error('with --spec, give the output path')
        output = args.input
        spec = RenderSpec.load(args.spec)
    else:
        if not (args.input and args.output):
            ap.error('an input file and an output path are required')
        output = args.output
        if any([args.custom_font_b, args.custom_font_c, args.custom_font_d]) and not args.custom_font:
            ap.error('alternate fonts require --custom-font')
        try:
            spec = spec_from_args(args)
        except ValueError as error:
            ap.error(str(error))

    if args.save_spec:
        print(f"Wrote {spec.save(args.save_spec)}", file=sys.stderr)

    render(spec, output, keep_html=args.keep_html, analyze=args.analyze)
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
