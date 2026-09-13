"""Build a deterministic stand-in for a personal handwriting hand.

These are not handwriting — the glyphs are plain geometry — but they carry the
characters and the sample geometry that tests/browser_handwriting.py needs, so
that suite can run on a machine with no personal fonts, and in CI.

Four variants are written, each with its own PostScript name, because the suite
checks which face Chromium actually selected. ``#`` is deliberately left out:
the suite asserts that an uncovered character is reported as a fallback.

    python3 tests/synthetic_hand.py OUTDIR
"""
import json
import string
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

UPM = 1000
ASCENT, DESCENT = 800, -200
VARIANTS = 'ABCD'

# Everything the suite renders, minus '#', which must stay uncovered.
COVERED = (string.ascii_letters + string.digits
           + " .,;:!?'\"()[]{}-+=/*<>|"
           + 'μβαγδθλπσφω'
           + '√→∑∫±×÷≤≥≠∞')

# Source-pixel sample geometry (x right, y down), the shape of what
# custom_font/stroke_profiles.py extracts from real bracket and arrow samples.
BRACKET_HEIGHT, BRACKET_WIDTH, BRACKET_CAP = 200, 36, 40
ARROW_WIDTH, ARROW_HEIGHT = 130, 100


def _rect(pen, x0, y0, x1, y1):
    """One closed contour, always the same winding so contours never cancel."""
    pen.moveTo((x0, y0))
    pen.lineTo((x0, y1))
    pen.lineTo((x1, y1))
    pen.lineTo((x1, y0))
    pen.closePath()


def _radical(pen):
    """A tick-and-bar, so the extracted radical outline is recognisably one."""
    pen.moveTo((40, 300))
    pen.lineTo((130, 60))
    pen.lineTo((200, 620))
    pen.lineTo((620, 620))
    pen.lineTo((620, 680))
    pen.lineTo((170, 680))
    pen.lineTo((115, 250))
    pen.lineTo((90, 330))
    pen.closePath()


def _glyph(character, variant_index):
    """A stem and a crossbar, proportioned from the codepoint so characters are
    distinguishable and each variant differs a little from the others."""
    pen = TTGlyphPen(None)
    if character == '√':
        _radical(pen)
        return pen.glyph(), 660
    code = ord(character)
    lean = variant_index * 12
    height = 380 + (code % 7) * 60          # 380..740
    width = 200 + (code % 5) * 70           # 200..480
    bar_y = 120 + (code % 4) * 90
    _rect(pen, 60 + lean, 0, 60 + lean + 90, height)
    _rect(pen, 60 + lean, bar_y, 60 + lean + width, bar_y + 90)
    return pen.glyph(), width + 220 + lean


def build_font(path, variant_index, family='Synthetic Hand'):
    variant = VARIANTS[variant_index]
    order = ['.notdef', 'space'] + [f'u{ord(c):04X}' for c in COVERED]
    glyphs = {'.notdef': TTGlyphPen(None).glyph(), 'space': TTGlyphPen(None).glyph()}
    metrics = {'.notdef': (600, 0), 'space': (300, 0)}
    for character in COVERED:
        name = f'u{ord(character):04X}'
        glyph, advance = _glyph(character, variant_index)
        glyphs[name] = glyph
        metrics[name] = (advance, 60)

    builder = FontBuilder(UPM, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({ord(c): f'u{ord(c):04X}' for c in COVERED} | {0x20: 'space'})
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)
    full = f'{family} {variant}'
    builder.setupNameTable({
        'familyName': full,
        'styleName': 'Regular',
        'uniqueFontIdentifier': f'{full} test fixture',
        'fullName': full,
        'psName': full.replace(' ', ''),
        'version': '1.0',
    })
    builder.setupOS2(sTypoAscender=ASCENT, sTypoDescender=DESCENT,
                     usWinAscent=ASCENT, usWinDescent=-DESCENT)
    builder.setupPost()
    path.parent.mkdir(parents=True, exist_ok=True)
    builder.save(path)
    return path


def bracket_profile(variant_index):
    lean = variant_index * 2
    left = [[BRACKET_WIDTH - 6, 4], [6 + lean, 4],
            [6 + lean, BRACKET_HEIGHT - 4], [BRACKET_WIDTH - 6, BRACKET_HEIGHT - 4]]
    right = [[6, 4], [BRACKET_WIDTH - 6 - lean, 4],
             [BRACKET_WIDTH - 6 - lean, BRACKET_HEIGHT - 4], [6, BRACKET_HEIGHT - 4]]
    shape = {'width': BRACKET_WIDTH, 'height': BRACKET_HEIGHT, 'capHeight': BRACKET_CAP}
    return {'[': {'points': left, **shape}, ']': {'points': right, **shape}}


def arrow_profile(variant_index):
    tip = ARROW_WIDTH - 10
    mid = ARROW_HEIGHT // 2
    spread = 20 + variant_index * 2
    return {'shaft': [[4, mid], [tip, mid]],
            'head': [[[tip, mid], [tip - 24, mid - spread]],
                     [[tip, mid], [tip - 24, mid + spread]]],
            'width': ARROW_WIDTH, 'height': ARROW_HEIGHT}


def build(directory, prefix='BigyanHand'):
    """Write four variants plus their .handwriting.json sidecars. Returns paths."""
    directory = Path(directory)
    written = []
    for index, variant in enumerate(VARIANTS):
        path = directory / f'{prefix}-{variant}.ttf'
        build_font(path, index)
        # One pen weight across every variant, so a matrix does not change
        # bracket thickness when the seed picks a different sample.
        path.with_suffix('.handwriting.json').write_text(json.dumps({
            'referenceStrokeEm': 0.055,
            'brackets': bracket_profile(index),
            'arrow': arrow_profile(index),
        }, indent=2), encoding='utf-8')
        written.append(path)
    return written


if __name__ == '__main__':
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('output/synthetic-hand')
    for path in build(target):
        print(path)
