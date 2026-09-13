#!/usr/bin/env python3
"""Generate two # handwriting samples and their extraction manifest.

    python3 custom_font/supplemental_template_gen.py
    python3 custom_font/extract_glyphs.py filled.pdf output/manifest_hash.json \
        my_font/glyphs_hash_a --variant A

Extract A and B separately; patch A/C fonts from sample A, B/D from sample B
using build_font.py --base-font FONT --metrics-in SHARED_METRICS.
"""
import argparse
import json
from pathlib import Path

from charset import safe_name

HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE.parent / 'output'
PAGE_SIZE = (8.5, 11.0)


def build_manifest():
    cells = []
    for index, variant in enumerate(('A', 'B')):
        cells.append({
            'char': '#',
            'safe_name': safe_name('#'),
            'variant': variant,
            'label': f'Sample {index + 1}',
            'note': 'Fonts A / C' if variant == 'A' else 'Fonts B / D',
            # Match the alphabet template's box and guide dimensions because
            # build_font reuses those samples' scale in shared metrics.
            'rect_in': [2.05 + index * 3.30, 3.10, 1.10, 1.10],
            'baseline_frac': 0.68,
            'xheight_frac': 0.40,
        })
    inset, size = 0.28, 0.16
    return {
        'page_size_in': list(PAGE_SIZE),
        'set': 'hash',
        'label': 'Two number-sign samples',
        'registration_marks_in': [
            [inset, inset, size, size],
            [PAGE_SIZE[0] - inset - size, inset, size, size],
            [inset, PAGE_SIZE[1] - inset - size, size, size],
            [PAGE_SIZE[0] - inset - size, PAGE_SIZE[1] - inset - size, size, size],
        ],
        'pages': [{'name': 'hash', 'title': 'Number sign #', 'page_index': 0, 'cells': cells}],
    }


def generate_pdf(path, manifest):
    """Keep all guides light enough for the existing ink-threshold extractor."""
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen.canvas import Canvas

    inch = 72
    page_w, page_h = (n * inch for n in PAGE_SIZE)
    canvas = Canvas(str(path), pagesize=(page_w, page_h))
    canvas.setTitle('Handwriting samples - number sign #')
    canvas.setAuthor('Handwriting font pipeline')

    def text(x, y, value, size=11, color='#444444', font='Helvetica'):
        canvas.setFillColor(HexColor(color))
        canvas.setFont(font, size)
        canvas.drawString(x * inch, page_h - y * inch, value)

    text(1.05, 1.14, 'Your handwritten #', 24, '#202020', 'Helvetica-Bold')
    text(1.05, 1.58, 'Write one number sign in each box using your usual dark pen.', 11)
    text(1.05, 1.84, 'Use the same pen thickness and letter size as your alphabet samples.', 11)
    text(1.05, 2.10, 'Let each sample vary naturally. Use the blue line as the baseline.', 11)

    for cell in manifest['pages'][0]['cells']:
        x, y, w, h = cell['rect_in']
        text(x, y - 0.19, cell['label'], 12, '#333333', 'Helvetica-Bold')
        canvas.setStrokeColor(HexColor('#BBBBBB'))
        canvas.setLineWidth(0.7)
        canvas.rect(x * inch, page_h - (y + h) * inch, w * inch, h * inch)
        for fraction, color, dash in ((cell['xheight_frac'], '#CFE0F0', [3, 3]),
                                      (cell['baseline_frac'], '#8FB7E0', [])):
            canvas.setStrokeColor(HexColor(color))
            canvas.setDash(dash)
            yy = page_h - (y + h * fraction) * inch
            canvas.line(x * inch, yy, (x + w) * inch, yy)
        canvas.setDash([])
        # Labels remain outside the crop; no ghost glyph can contaminate ink.
        text(x, y + h + 0.30, cell['note'], 10, '#666666')

    text(1.05, 5.48, 'When finished', 13, '#333333', 'Helvetica-Bold')
    text(1.05, 5.80, 'Export this full page as a PDF and place it in the my_font folder.', 11)
    text(1.05, 6.08, 'Keep the page size and all four red corner marks unchanged.', 11)
    text(1.05, 6.62, 'These two samples add # to all four handwriting fonts.', 11)
    for x, y, w, h in manifest['registration_marks_in']:
        canvas.setFillColor(HexColor('#E23A3A'))
        canvas.rect(x * inch, page_h - (y + h) * inch, w * inch, h * inch, fill=1, stroke=0)
    canvas.showPage()
    canvas.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output_pdf', nargs='?', type=Path, default=DEFAULT_OUTPUT / 'template_hash.pdf')
    parser.add_argument('output_manifest', nargs='?', type=Path, default=DEFAULT_OUTPUT / 'manifest_hash.json')
    args = parser.parse_args()
    args.output_pdf.parent.mkdir(parents=True, exist_ok=True)
    args.output_manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest()
    generate_pdf(args.output_pdf, manifest)
    args.output_manifest.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Generated {args.output_pdf} (1 page, 2 samples)')
    print(f'Generated {args.output_manifest}')


if __name__ == '__main__':
    main()
