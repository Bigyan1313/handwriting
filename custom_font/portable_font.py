"""Portable Potrace + fontTools backend (pip install potracer fonttools)."""
from pathlib import Path
from PIL import Image
from fontTools.fontBuilder import FontBuilder
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
import potrace
import statistics


def patch_glyphs(font, glyphs, advances, cmap):
    """Replace existing characters or append new ones without renaming old glyphs.

    Keep all Unicode cmap subtables in agreement, including format 12 for
    characters outside the BMP. FontTools recalculates glyf/maxp/hhea counts
    when saving the updated glyph order and horizontal metrics.
    """
    if 'glyf' not in font:
        raise ValueError('Base font patching requires a TrueType glyf font')
    old_cmap = font.getBestCmap() or {}
    order = font.getGlyphOrder()
    used_names = set(order)
    updates = {}
    for code, traced_name in cmap.items():
        target = old_cmap.get(code)
        if target is None:
            target = traced_name
            suffix = 1
            while target in used_names:
                target = f'{traced_name}.sample{suffix}'
                suffix += 1
            order.append(target)
            used_names.add(target)
        font['glyf'][target] = glyphs[traced_name]
        font['hmtx'][target] = advances[traced_name]
        updates[code] = target
    font.setGlyphOrder(order)

    unicode_tables = [t for t in font['cmap'].tables
                      if t.isUnicode() and hasattr(t, 'cmap')]
    # A format-4 cmap keeps new BMP glyphs visible in older renderers. A
    # format-12 table must contain the complete map, not just new glyphs.
    combined = {**old_cmap, **updates}
    if not any(t.format == 4 for t in unicode_tables):
        table = CmapSubtable.newSubtable(4)
        table.platformID, table.platEncID, table.language = 3, 1, 0
        table.cmap = {c: n for c, n in combined.items() if c < 0xFFFF}
        font['cmap'].tables.append(table)
        unicode_tables.append(table)
    if any(code > 0xFFFF for code in combined) and not any(t.format == 12 for t in unicode_tables):
        table = CmapSubtable.newSubtable(12)
        table.platformID, table.platEncID, table.language = 3, 10, 0
        table.cmap = dict(combined)
        font['cmap'].tables.append(table)
        unicode_tables.append(table)
    for table in unicode_tables:
        # Format 14 contains variation sequences instead of direct mappings.
        if table.format == 14:
            continue
        maximum = 0xFF if table.format == 0 else 0xFFFF if table.format in (2, 4, 6) else 0x10FFFF
        table.cmap.update({code: name for code, name in updates.items() if code <= maximum})
    if 'OS/2' in font:
        metrics = font['OS/2']
        metrics.usWinAscent = max(metrics.usWinAscent, max(g.yMax for g in glyphs.values()))
        metrics.usWinDescent = max(metrics.usWinDescent, max(-g.yMin for g in glyphs.values()))
        metrics.recalcUnicodeRanges(font)


def trace_glyph(path, scale, below, bearing=35):
    with Image.open(path) as source:
        bitmap = source.convert('L')
    outline = potrace.Bitmap(bitmap).trace(turdsize=0, opttolerance=0.15)
    sink = TTGlyphPen(None)
    pen = TransformPen(Cu2QuPen(sink, max_err=0.5, reverse_direction=True),
                       (scale, 0, 0, -scale, bearing, (bitmap.height - below) * scale))
    def xy(p):
        return p.x, p.y
    for curve in outline:
        pen.moveTo(xy(curve.start_point))
        for segment in curve:
            if segment.is_corner:
                pen.lineTo(xy(segment.c))
                pen.lineTo(xy(segment.end_point))
            else:
                pen.curveTo(xy(segment.c1), xy(segment.c2), xy(segment.end_point))
        pen.closePath()
    glyph = sink.glyph()
    if not glyph.numberOfContours:
        raise ValueError(f'No outline found in {path}')
    glyph.recalcBounds(None)
    return glyph, round(bitmap.width * scale + 2 * bearing)


def build(meta, placements, scale_for, output, name, ascent, descent, base_font=None):
    glyphs, advances, cmap, widths = {}, {}, {}, []
    for key, info in sorted(meta.items()):
        ch = info['char']
        glyph, width = trace_glyph(Path(info['dir']) / (key + '.png'), scale_for(key), placements[key]['below'])
        glyph_name = f'uni{ord(ch):04X}'
        glyphs[glyph_name] = glyph
        advances[glyph_name] = (width, glyph.xMin)
        cmap[ord(ch)] = glyph_name
        if ch.isalnum():
            widths.append(width)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if base_font:
        with TTFont(base_font) as font:
            patch_glyphs(font, glyphs, advances, cmap)
            font.save(output)
    else:
        fb = FontBuilder(1000, isTTF=True)
        empty = TTGlyphPen(None).glyph()
        fb.setupGlyphOrder(['.notdef', 'space'] + list(glyphs))
        fb.setupCharacterMap({32: 'space', **cmap})
        fb.setupGlyf({'.notdef': empty, 'space': empty, **glyphs})
        fb.setupHorizontalMetrics({'.notdef': (500, 0), 'space': (round(statistics.median(widths) * .58) if widths else 260, 0), **advances})
        fb.setupHorizontalHeader(ascent=ascent, descent=-descent, lineGap=0)
        fb.setupNameTable(dict(familyName=name, styleName='Regular', uniqueFontIdentifier=name + ' Regular', fullName=name, psName=name.replace(' ', '')))
        fb.setupOS2(sTypoAscender=ascent, sTypoDescender=-descent, sTypoLineGap=0,
                    usWinAscent=max(ascent, max(g.yMax for g in glyphs.values())),
                    usWinDescent=max(descent, -min(g.yMin for g in glyphs.values())))
        fb.setupPost()
        fb.setupMaxp()
        fb.save(output)
    print(f'Built {output} — {len(glyphs)} traced glyphs' + (' (patched existing font)' if base_font else ''))


def align_metrics(output, reference):
    """Use identical line-box metrics while preserving every glyph outline."""
    with TTFont(reference) as source, TTFont(output) as font:
        if source['head'].unitsPerEm != font['head'].unitsPerEm:
            raise ValueError('Metric reference must use the same units per em')
        for table, fields in [('hhea', ['ascent', 'descent', 'lineGap']),
                              ('OS/2', ['sTypoAscender', 'sTypoDescender', 'sTypoLineGap', 'usWinAscent', 'usWinDescent'])]:
            for field in fields:
                setattr(font[table], field, getattr(source[table], field))
        font.save(output)
