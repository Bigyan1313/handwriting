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
import subprocess
import random
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

import clean as cleaner
import paper as paperlib

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


def paper_layout(paper_path: str, font_path: str, font_size: int):
    """Work out the CSS geometry needed to write onto a supplied ruled page:
    page size, line-height matching the rules, and the top/left padding that
    puts the first baseline on the first rule and clears the margin rule."""
    path = Path(paper_path)
    img = paperlib.load_page(path)
    rules = paperlib.detect_rules(img)

    page_w_in, page_h_in = 8.5, 11.0
    if path.suffix.lower() == ".pdf":
        out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True).stdout
        m = _re.search(r"Page size:\s+([\d.]+) x ([\d.]+) pts", out)
        if m:
            page_w_in, page_h_in = float(m.group(1)) / 72.0, float(m.group(2)) / 72.0
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

    two_variants_js = "true" if (len(two_variants) > 1 and hand_math) else "false"

    # Handwritten stretchy delimiters need a custom font to take glyphs from,
    # and the font's own vertical metrics to place them.
    hand_delims_js = "false"
    font_asc, font_desc, font_upem = 800, 200, 1000
    if custom_font_path:
        try:
            font_asc, font_desc, font_upem = font_vmetrics(custom_font_path)
            if hand_math and hand_delims:
                hand_delims_js = "true"
        except Exception:
            pass

    if paper:
        line_height = int(round(paper["line_height"]))
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
    base_top = paper['pad_top'] if paper else 0
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

/* Second version of the same handwriting: characters randomly tagged .vb
   render from the alternate font, so repeated letters aren't identical
   stamps of each other. */
.vb {{ font-family: 'HandwritingFontB', cursive !important; }}

.para {{ margin: 0; }}
.para + .para {{ margin-top: 2px; }}

.display-math-src {{
  display: block;
  margin: 10px 0 14px 12px;
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

  var VARIANTS = {json.dumps(['HandwritingFont' + x for x in two_variants])};
  var layoutConfig = {json.dumps({'seed': seed, 'jitter': jitter, 'lineHeight': line_height, 'pageHeight': page_height, 'baseTop': base_top})};
  { (HERE / 'layout.js').read_text() }
  function mkRand(seed) {{
    var s = seed >>> 0;
    return function () {{ s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }};
  }}
  const handwritingConfig = {json.dumps({'resources': resources, 'seed': seed, 'handMath': hand_math, 'handDelims': bool(custom_font_path and hand_math and hand_delims), 'bracketStrokeScale': bracket_stroke_scale})};
  {(HERE / 'handwriting.js').read_text()}

  // Font choice and geometry are completed before measuring equation lines.
  // Swap KaTeX's stretchy delimiters for the handwritten ones. KaTeX draws
  // tall brackets as SVG paths (not glyphs), so they can't be font-swapped:
  // instead the matching character is read from the LaTeX source in order,
  // measured with canvas ink metrics, and scaled to cover the same box.
  var HAND_DELIMS = {hand_delims_js};
  var FONT_A = 'HandwritingFont', FONT_B = 'HandwritingFontB';
  var F_ASC = {font_asc}, F_DESC = {font_desc}, F_UPEM = {font_upem};
  var DELIM_MAP = {{'\\\\{{':'{{', '\\\\}}':'}}', '\\\\|':'|', '\\\\lbrack':'[',
                   '\\\\rbrack':']', '\\\\vert':'|', '\\\\Vert':'|',
                   '[':'[', ']':']', '(':'(', ')':')', '|':'|'}};
  var ENV_DELIMS = {{
    'pmatrix': ['(', ')'],
    'bmatrix': ['[', ']'],
    'Bmatrix': ['{{', '}}'],
    'vmatrix': ['|', '|'],
    'Vmatrix': ['|', '|'],
    'cases':   ['{{', null],
    'dcases':  ['{{', null],
    'rcases':  [null, '}}'],
    'drcases': [null, '}}']
  }};

  function delimsFromTex(tex) {{
    var out = [];
    var re = /\\\\(?:(left|right)(?![a-zA-Z])\\s*(\\\\[a-zA-Z]+|\\\\[^a-zA-Z\\s]|[^\\s])|(begin|end)\\{{([a-zA-Z]+)\\}})/g;
    var m;
    while ((m = re.exec(tex)) !== null) {{
      if (m[1]) {{
        var raw = m[2];
        if (raw === '.') continue;
        out.push(DELIM_MAP[raw] || (raw.length === 1 ? raw : null));
      }} else if (m[3]) {{
        var action = m[3];
        var env = m[4];
        if (ENV_DELIMS[env]) {{
          var ch = action === 'begin' ? ENV_DELIMS[env][0] : ENV_DELIMS[env][1];
          if (ch) out.push(ch);
        }}
      }}
    }}
    return out;
  }}
  function inkMetrics(ch, family, size) {{
    var cx = document.createElement('canvas').getContext('2d');
    cx.font = size + "px '" + family + "'";
    var m = cx.measureText(ch);
    return {{asc: m.actualBoundingBoxAscent, desc: m.actualBoundingBoxDescent,
            left: m.actualBoundingBoxLeft, right: m.actualBoundingBoxRight}};
  }}
  // A .delimsizing box doesn't cover the pieces it draws (they overflow it),
  // so take the union of its descendants' boxes.
  function visualRect(el) {{
    var r = el.getBoundingClientRect();
    var top = r.top, bot = r.bottom, left = r.left, right = r.right;
    el.querySelectorAll('*').forEach(function (n) {{
      var b = n.getBoundingClientRect();
      if (!b.height || !b.width) return;
      top = Math.min(top, b.top); bot = Math.max(bot, b.bottom);
      left = Math.min(left, b.left); right = Math.max(right, b.right);
    }});
    return {{dTop: top - r.top, dLeft: left - r.left, height: bot - top, width: right - left}};
  }}
  function origInk(el, ch) {{
    var cs = getComputedStyle(el);
    var cx = document.createElement('canvas').getContext('2d');
    cx.font = parseFloat(cs.fontSize) + 'px ' + cs.fontFamily;
    var m = cx.measureText(ch);
    var probe = document.createElement('span');
    probe.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline;';
    el.appendChild(probe);
    var by = probe.getBoundingClientRect().top;   // sits on the text baseline
    probe.remove();
    var r = el.getBoundingClientRect();
    var h = m.actualBoundingBoxAscent + m.actualBoundingBoxDescent;
    var w = m.actualBoundingBoxLeft + m.actualBoundingBoxRight;
    return {{dTop: (by - m.actualBoundingBoxAscent) - r.top, dLeft: 0,
            height: h, width: Math.max(w, r.width)}};
  }}
  function handDelims(root, pick) {{
    var wanted = delimsFromTex(root.dataset.tex || '');
    Array.from(root.querySelectorAll('.delimsizing')).forEach(function (el, i) {{
      var ch = (el.textContent || '').replace(/[\\u200b\\\\s]/g, '');
      if (!ch) ch = wanted[i] || null;
      if (!ch || '[]{{}}()|'.indexOf(ch) < 0 || ch === '[' || ch === ']') return;
      var pc = el.parentElement ? String(el.parentElement.className) : '';
      if ('([{{'.indexOf(ch) >= 0 && pc.indexOf('mclose') >= 0) return;
      if (')]}}'.indexOf(ch) >= 0 && pc.indexOf('mopen') >= 0) return;
      // Tall delimiters are drawn as child SVG/vlist pieces (union their
      // boxes). Small ones are a bare text glyph that overflows its own box,
      // so measure that glyph's ink against the element's baseline instead.
      var v = el.children.length ? visualRect(el) : origInk(el, ch);
      if (!v || !v.height) return;
      var fam = pick();
      var S = 100, im = inkMetrics(ch, fam, S);
      var inkH = im.asc + im.desc, inkW = im.left + im.right;
      if (!inkH || !inkW) return;
      var sy = v.height / inkH;
      var sx = Math.min(v.width / inkW, sy);
      var baseOff = -S / 2 + S * F_ASC / F_UPEM;
      var tx = v.dLeft + im.left * sx;
      var ty = v.dTop - (baseOff - im.asc) * sy;
      el.style.position = 'relative';
      // Small delimiters are a bare text node on the element itself; tall ones
      // are child SVG/vlist pieces. Hide both kinds before drawing over them.
      var ink = getComputedStyle(el).color;
      el.style.color = 'transparent';
      Array.from(el.children).forEach(function (c) {{ c.style.visibility = 'hidden'; }});
      var g = document.createElement('span');
      g.textContent = ch;
      g.style.cssText = "position:absolute;left:0;top:0;display:block;line-height:0;color:" + ink + ";"
        + "font-family:'" + fam + "';font-size:" + S + "px;white-space:pre;"
        + "transform-origin:0 0;transform:translate(" + tx + "px," + ty + "px) scale("
        + sx + "," + sy + ");";
      el.appendChild(g);
    }});
  }}
  decorateProse();
  prepareEquations();
  document.querySelectorAll('.math-src, .display-math-src').forEach(root => decorateMath(root));
  if (HAND_DELIMS) {{
    var dr = mkRand({seed} + 7919);
    var pick = function () {{ return VARIANTS[Math.floor(dr() * VARIANTS.length)]; }};
    document.querySelectorAll('.math-src, .display-math-src').forEach(function (root) {{
      try {{ handDelims(root, pick); }} catch (e) {{}}
    }});
  }}

  // Keep the ruled grid: pad each display-math block out to a whole number
  // of ruled lines so the prose after it lands back on a line.
  var LH = {line_height};
  document.querySelectorAll('.display-math-src').forEach(function (el) {{
    var st = getComputedStyle(el);
    var mt = parseFloat(st.marginTop) || 0, mb = parseFloat(st.marginBottom) || 0;
    var total = el.offsetHeight + mt + mb;
    var target = Math.ceil(total / LH) * LH;
    el.style.marginBottom = (mb + (target - total)) + 'px';
  }});
  paginate();
  auditHandwriting();
  window.__renderDone = true;
  }});
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="input text/markdown file with the solution")
    ap.add_argument("output", help="output PDF path")
    ap.add_argument("--font", choices=list(FONTS.keys()), default="kalam")
    ap.add_argument("--custom-font", metavar="PATH", help="use your own .ttf (e.g. one built from your handwriting) instead of --font")
    ap.add_argument("--paper", metavar="PATH", help="write onto this ruled page (PDF or image) instead of the generated ruled paper")
    ap.add_argument("--custom-font-b", metavar="PATH", help="second variant of your handwriting; characters alternate between the two")
    ap.add_argument("--font-size", type=int, default=None, help="body text size in px (default 22; custom fonts often want more)")
    ap.add_argument("--hand-math", action="store_true", help="render the math in the handwriting font too (KaTeX still does the layout)")
    ap.add_argument("--no-hand-delims", action="store_true", help="keep KaTeX's brackets instead of your handwritten ones (only relevant with --hand-math)")
    ap.add_argument("--math-scale", type=float, default=1.28, help="size bump for hand-rendered math (default 1.28)")
    ap.add_argument("--line-height", type=int, default=40, help="ruled line spacing in px (default 40)")
    ap.add_argument("--seed", type=int, default=1, help="random seed for jitter (change for a different look)")
    ap.add_argument("--clean", action="store_true", help="input is already clean LaTeX/Markdown -- skip messy-paste cleanup")
    ap.add_argument("--no-jitter", action="store_true", help="disable per-word jitter (uniform font look)")
    ap.add_argument("--keep-html", metavar="PATH", help="also save the intermediate HTML for inspection")
    ap.add_argument('--custom-font-c', metavar='PATH')
    ap.add_argument('--custom-font-d', metavar='PATH')
    ap.add_argument('--bracket-stroke-scale', type=float, default=1.0, help='bracket pen width relative to nearby handwriting (default 1.0)')
    ap.add_argument('--analyze', action='store_true', help='print measured layout report and save JSON beside PDF')
    args = ap.parse_args()
    if any([args.custom_font_b, args.custom_font_c, args.custom_font_d]) and not args.custom_font:
        ap.error('alternate fonts require --custom-font')
    if not 0 < args.bracket_stroke_scale < float('inf'):
        ap.error('bracket stroke scale must be finite and positive')
    if args.line_height <= 0 or (args.font_size is not None and args.font_size <= 0):
        ap.error('font size and line height must be positive')

    if args.font_size is None and not args.paper:
        args.font_size = 22

    raw = Path(args.input).read_text(encoding='utf-8-sig')

    if args.clean:
        text = raw
        notes = []
    else:
        text, notes = cleaner.clean_messy_text(raw)

    if notes:
        print("Cleanup notes:", file=sys.stderr)
        for n in notes:
            flag = "  [!] " if n.startswith("WARNING") else "  - "
            print(flag + n, file=sys.stderr)

    font_for_metrics = args.custom_font or str(FONT_DIR / FONTS[args.font]["regular"])

    paper = None
    if args.paper:
        font_size = args.font_size
        if font_size is None:
            # Size the writing to the paper: aim for an x-height around 40% of
            # the rule spacing, but never let ascender+descender overrun the
            # spacing by more than a little.
            probe, rules0 = paper_layout(args.paper, font_for_metrics, 22)
            if probe:
                asc, desc, upem = font_vmetrics(font_for_metrics)
                lh = probe["line_height"]
                font_size = int(round(min(0.40 * lh / 0.341, 1.15 * lh * upem / (asc + desc))))
                print(f"Auto font size for this paper: {font_size}px "
                      f"(rule spacing {lh:.1f}px)", file=sys.stderr)
            else:
                font_size = 22
        args.font_size = font_size
        paper, rules = paper_layout(args.paper, font_for_metrics, args.font_size)
        print(paperlib.describe(rules), file=sys.stderr)
        if paper is None:
            print("  -> using the generated ruled paper instead.", file=sys.stderr)

    blocks = cleaner.parse_blocks(text, grouped=True)
    html_doc = build_html(blocks, args.font, args.seed, jitter=not args.no_jitter,
                          custom_font_path=args.custom_font,
                          font_size=args.font_size, line_height=args.line_height,
                          hand_math=args.hand_math, math_scale=args.math_scale,
                          custom_font_b_path=args.custom_font_b, paper=paper,
                          hand_delims=not args.no_hand_delims,
                          custom_font_c_path=args.custom_font_c, custom_font_d_path=args.custom_font_d,
                          bracket_stroke_scale=args.bracket_stroke_scale)

    html_path = Path(args.keep_html) if args.keep_html else (HERE / "output" / "_render.html")
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
        if args.analyze:
            report_path = Path(args.output).with_suffix('.layout.json')
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2))
        if report['warnings']:
            print('Layout warnings: ' + '; '.join(report['warnings']), file=sys.stderr)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        page.pdf(path=args.output, print_background=True, prefer_css_page_size=True)
        browser.close()

    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
