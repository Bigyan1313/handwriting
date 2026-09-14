#!/usr/bin/env python3
"""
Assemble extracted glyph PNGs (from extract_glyphs.py) into a real TTF.

Each glyph is scaled by one shared factor (so the natural size differences
between your letters survive), placed on the baseline according to normal
typographic rules for that character, vectorized with potrace, and imported
into a FontForge glyph slot.

Why the fixed 1000x1000 canvas: FontForge's SVG import scales by
em / max(width, height) and puts the canvas top at the font's ascent line.
Trace a canvas exactly one em square and that becomes a clean 1:1 mapping --
font_x = pixel_x, font_y = ascent - pixel_y -- so no post-import transform
math is needed (verified empirically against corner markers).

Where a letter sits vertically is NOT taken from where it was written in its
box: people don't write exactly on the guide line, and raw offsets can span
80+ px, which renders as badly bouncing text. Each glyph is placed by what
kind of character it is -- sits on the baseline, hangs below it, hangs from
the cap line, or centres on the x-height.

Several glyph directories can be merged into one font (alphabet + math), and
metrics can be shared between builds so a second variant of the same
handwriting comes out exactly the same size:

    python3.12 build_font.py out/A.ttf --glyphs glyphs_set1 --glyphs glyphs_math \\
        --name "My Hand" --metrics-out out/metrics.json
    python3.12 build_font.py out/B.ttf --glyphs glyphs_set2 --glyphs glyphs_math \\
        --name "My Hand B" --metrics-in out/metrics.json

Must run under python3.12 (the interpreter the fontforge module is built
against in this environment).
"""
import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import fontforge
except ImportError:
    fontforge = None
from PIL import Image

EM = 1000
VERTICAL_FILL = 0.97      # fraction of the em the tallest-to-deepest ink spans
LEFT_BEARING = 35
RIGHT_BEARING = 35
SPACE_RATIO = 0.58        # space advance, as a fraction of median letter advance
CANVAS = EM               # must equal em for the 1:1 import mapping

X_HEIGHT_CHARS = "acemnorsuvwxz"
CAP_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Delimiters are drawn deliberately oversized on the template ("draw tall")
# and get stretched to fit at render time, so they're normalised to a fixed
# height of their own and kept out of the shared scale calculation --
# otherwise one tall bracket would shrink the entire alphabet.
DELIMITERS = set("[]{}|()")
DELIM_HEIGHT_CAPS = 1.30      # delimiter height, in multiples of cap height
DELIM_DROP_X = 0.22           # how far below the baseline a delimiter sits

# How far below the baseline the ink should hang, as a fraction of the
# glyph's OWN ink height.
DESCEND_OWN_HEIGHT = {
    "g": 0.36, "j": 0.36, "p": 0.38, "q": 0.38, "y": 0.38,
    "β": 0.30, "γ": 0.35, "ρ": 0.35, "φ": 0.30, "μ": 0.30, "∫": 0.35,
}
# ... or as a fraction of the x-height (small marks, delimiters)
DESCEND_X_HEIGHT = {
    ",": 0.35, ";": 0.35, "/": 0.15,
    "(": DELIM_DROP_X, ")": DELIM_DROP_X, "[": DELIM_DROP_X,
    "]": DELIM_DROP_X, "{": DELIM_DROP_X, "}": DELIM_DROP_X,
    "|": DELIM_DROP_X,
}
# Ink TOP sits at cap height
HANG_FROM_CAP = set("'\"°′")
# Ink centred on half the x-height
CENTER_ON_XHEIGHT = set("-=+−×÷±∓·≠≈≡<>≤≥∝≅→←↔⇒⇔∥")


def measure(meta):
    def med(chars):
        hs = [m["height_px"] for m in meta.values() if m["char"] in chars]
        return statistics.median(hs) if hs else 0
    return med(X_HEIGHT_CHARS), med(CAP_CHARS)


def offset_below(ch, h, x_height, cap_height):
    """How far this glyph's ink bottom sits BELOW the baseline, in source
    pixels. Negative means the ink floats above the baseline."""
    if ch in DESCEND_OWN_HEIGHT:
        return DESCEND_OWN_HEIGHT[ch] * h
    if ch in DESCEND_X_HEIGHT:
        return DESCEND_X_HEIGHT[ch] * x_height
    if ch in HANG_FROM_CAP:
        return -(cap_height - h)
    if ch in CENTER_ON_XHEIGHT:
        return -(0.5 * x_height - h / 2.0)
    return 0.0


def load_meta(glyph_dirs):
    """Merge meta.json from several glyph dirs; first directory wins on
    duplicate characters. Returns {safe_name: {..., 'dir': Path}}."""
    merged, seen = {}, {}
    for d in glyph_dirs:
        meta_path = d / "meta.json"
        if not meta_path.exists():
            sys.exit(f"No meta.json in {d} -- run extract_glyphs.py on it first.")
        for name, info in json.loads(meta_path.read_text()).items():
            if info["char"] in seen:
                continue
            info = dict(info)
            info["dir"] = str(d)
            merged[name] = info
            seen[info["char"]] = d
    return merged


def plan(meta, x_height, cap_height):
    """Per-glyph vertical placement plus the shared scale."""
    placements = {}
    for name, m in meta.items():
        ch, h = m["char"], m["height_px"]
        below = offset_below(ch, h, x_height, cap_height)
        placements[name] = {
            "below": below,
            "above": h - below,
            "delimiter": ch in DELIMITERS,
        }

    # Delimiters are excluded from the fit -- they're normalised separately.
    body = [p for p in placements.values() if not p["delimiter"]] or list(placements.values())
    max_above = max(p["above"] for p in body)
    max_below = max(p["below"] for p in body)
    scale = (EM * VERTICAL_FILL) / (max_above + max_below)

    ascent = int(round(max_above * scale)) + 10
    ascent = min(ascent, EM - int(round(max_below * scale)) - 10)
    return placements, scale, ascent, EM - ascent


def glyph_scale(name, meta, placements, scale, cap_height):
    """Delimiters get their own scale so they land at a fixed height."""
    if not placements[name]["delimiter"]:
        return scale
    h = meta[name]["height_px"]
    target_units = DELIM_HEIGHT_CAPS * cap_height * scale
    return target_units / h if h else scale


def make_canvas(png_path, below_px, scale, baseline_row):
    img = Image.open(png_path).convert("L")
    w, h = img.size
    new_w, new_h = max(1, round(w * scale)), max(1, round(h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("L", (CANVAS, CANVAS), 255)
    paste_y = round(baseline_row + below_px * scale - new_h)
    canvas.paste(img, (LEFT_BEARING, paste_y))
    return canvas, new_w


def trace(canvas, pbm_path, svg_path):
    canvas.point(lambda p: 255 if p > 128 else 0, mode="1").save(pbm_path)
    subprocess.run(
        ["potrace", "-s", "-u", "1", "-M", "0", "-o", str(svg_path), str(pbm_path)],
        check=True, capture_output=True,
    )


def build(glyph_dirs, out_path, family_name, metrics_in, metrics_out, backend="portable", base_font=None):
    meta = load_meta(glyph_dirs)
    if not meta:
        sys.exit("No glyphs found.")

    if metrics_in:
        m = json.loads(Path(metrics_in).read_text())
        x_height, cap_height = m["x_height"], m["cap_height"]
        scale, ascent, descent = m["scale"], m["ascent"], m["descent"]
        placements, _, _, _ = plan(meta, x_height, cap_height)
        print(f"Using shared metrics from {metrics_in}")
    else:
        x_height, cap_height = measure(meta)
        placements, scale, ascent, descent = plan(meta, x_height, cap_height)

    print(f"x-height {x_height:.0f}px  cap-height {cap_height:.0f}px  "
          f"scale {scale:.3f} units/px  ascent {ascent}  descent {descent}")
    print(f"-> x-height {x_height*scale:.0f} units, cap-height {cap_height*scale:.0f} units")

    if metrics_out:
        Path(metrics_out).write_text(json.dumps({
            "x_height": x_height, "cap_height": cap_height,
            "scale": scale, "ascent": ascent, "descent": descent,
        }, indent=2))

    if backend == 'portable' or (backend == 'auto' and fontforge is None) or base_font:
        try:
            from portable_font import build as portable_build
        except ImportError as error:
            sys.exit(f'The portable backend needs potracer and fonttools: {error}\n'
                     '    pip install -r custom_font/requirements-portable.txt')
        portable_build(meta, placements, lambda key: glyph_scale(key, meta, placements, scale, cap_height),
                       out_path, family_name, ascent, descent, base_font)
        return
    if fontforge is None:
        sys.exit('FontForge is not importable from this interpreter. Drop --backend '
                 'fontforge to use the portable backend, which needs no system packages.')
    font = fontforge.font()
    font.encoding = "UnicodeFull"
    font.em = EM
    font.ascent = ascent
    font.descent = descent
    font.familyname = family_name
    font.fontname = family_name.replace(" ", "")
    font.fullname = family_name

    letter_widths = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ok, failed = 0, []
        for name, info in sorted(meta.items()):
            ch = info["char"]
            png_path = Path(info["dir"]) / f"{name}.png"
            if not png_path.exists():
                failed.append(ch)
                continue
            try:
                gs = glyph_scale(name, meta, placements, scale, cap_height)
                canvas, ink_w = make_canvas(
                    png_path, placements[name]["below"], gs, ascent
                )
                pbm_path, svg_path = tmp / f"{name}.pbm", tmp / f"{name}.svg"
                trace(canvas, pbm_path, svg_path)

                glyph = font.createChar(ord(ch))
                glyph.importOutlines(str(svg_path))
                glyph.removeOverlap()
                glyph.simplify()
                glyph.correctDirection()
                glyph.width = int(ink_w + LEFT_BEARING + RIGHT_BEARING)
                if ch.isalnum():
                    letter_widths.append(glyph.width)
                ok += 1
            except Exception as e:
                failed.append(f"{ch} ({e})")

    space = font.createChar(ord(" "), "space")
    space.width = int(statistics.median(letter_widths) * SPACE_RATIO) if letter_widths else 260

    out_path.parent.mkdir(parents=True, exist_ok=True)
    font.generate(str(out_path))
    print(f"Built {out_path} -- {ok} glyph(s)" + (f", failed: {failed}" if failed else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output_ttf")
    ap.add_argument("--glyphs", action="append", required=True, metavar="DIR",
                    help="glyph directory (repeatable; earlier dirs win on duplicates)")
    ap.add_argument("--name", default="MyHandwriting")
    ap.add_argument("--metrics-in", metavar="FILE",
                    help="reuse metrics from a previous build (keeps variants the same size)")
    ap.add_argument("--metrics-out", metavar="FILE", help="write this build's metrics")
    ap.add_argument('--backend', choices=['portable', 'fontforge', 'auto'], default='portable',
                    help='outline backend: portable (default, pure pip) | fontforge | auto')
    ap.add_argument('--base-font', help='patch supplied glyphs in an existing TTF, preserving all other outlines')
    ap.add_argument("--metrics-font", help="match final line-box metrics to this reference TTF")
    args = ap.parse_args()

    build([Path(d) for d in args.glyphs], Path(args.output_ttf), args.name,
          args.metrics_in, args.metrics_out, args.backend, args.base_font)
    if args.metrics_font:
        from portable_font import align_metrics
        align_metrics(args.output_ttf, args.metrics_font)


if __name__ == "__main__":
    main()
