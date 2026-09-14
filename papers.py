"""Paper to write on: a few presets, and your own pages once imported.

A preset is a *description* — rule spacing, where the first rule sits, whether
there is a margin — not a stored image. Drawing it from that description means
its geometry is known exactly instead of being measured back out of a
rasterised page, and there are no page images in the repository.

Your own pages go the other way: the rules are found once with
``paper.detect_rules`` and cached, so a preset and an imported page are the
same kind of thing by the time anything renders.

    python3 papers.py list
    python3 papers.py import my-goodnotes-page.pdf --name goodnotes

Spacings are the real ones: wide (legal) ruled is 8.7 mm, college ruled
7.1 mm, narrow ruled 6.35 mm, each with a margin rule 1.25 in from the left.
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

import paper as paperlib

DPI = 150
LETTER_IN = (8.5, 11.0)
MM_PER_IN = 25.4

# The renderer's own palette, so generated paper matches the ink it carries.
PAPER_RGB = (252, 250, 244)
RULE_RGB = (150, 175, 215)
MARGIN_RGB = (214, 120, 120)

USER_PAPERS_DIR = Path.home() / '.handwriting' / 'papers'

PRESETS = {
    'ruled-wide': {
        'display': 'Ruled, wide (8.7 mm)',
        'kind': 'ruled', 'spacing_mm': 8.7, 'first_mm': 25.4, 'margin_mm': 31.75,
    },
    'college': {
        'display': 'College ruled (7.1 mm)',
        'kind': 'ruled', 'spacing_mm': 7.1, 'first_mm': 25.4, 'margin_mm': 31.75,
    },
    'ruled-narrow': {
        'display': 'Ruled, narrow (6.35 mm)',
        'kind': 'ruled', 'spacing_mm': 6.35, 'first_mm': 25.4, 'margin_mm': 31.75,
    },
    'graph-5mm': {
        'display': 'Graph paper (5 mm)',
        'kind': 'grid', 'spacing_mm': 5.0, 'first_mm': 10.0, 'margin_mm': None,
    },
    'dotted-5mm': {
        'display': 'Dot grid (5 mm)',
        'kind': 'dots', 'spacing_mm': 5.0, 'first_mm': 10.0, 'margin_mm': None,
    },
    'blank': {
        # No marks, but still a line rhythm to write on, or the text would have
        # no spacing to follow.
        'display': 'Blank',
        'kind': 'blank', 'spacing_mm': 7.1, 'first_mm': 25.4, 'margin_mm': None,
    },
}


def _px(mm, dpi=DPI):
    return mm / MM_PER_IN * dpi


def preset_geometry(name, dpi=DPI):
    """The same shape paper.detect_rules returns, computed rather than measured."""
    spec = PRESETS[name]
    width = int(round(LETTER_IN[0] * dpi))
    height = int(round(LETTER_IN[1] * dpi))
    spacing = _px(spec['spacing_mm'], dpi)
    first = _px(spec['first_mm'], dpi)
    margin = _px(spec['margin_mm'], dpi) if spec['margin_mm'] else None
    centers = []
    y = first
    while y < height - _px(12.0, dpi):
        centers.append(y)
        y += spacing
    return {
        'size_px': (width, height),
        'line_centers_px': centers,
        'line_spacing_px': spacing,
        'first_line_px': first,
        'margin_x_px': margin,
        'line_spacing_frac': spacing / height,
        'first_line_frac': first / height,
        'margin_x_frac': (margin / width) if margin is not None else None,
        'line_count': len(centers),
    }


def draw_preset(name, dpi=DPI):
    """Render a preset to an image, using the geometry above."""
    spec = PRESETS[name]
    rules = preset_geometry(name, dpi)
    width, height = rules['size_px']
    image = Image.new('RGB', (width, height), PAPER_RGB)
    draw = ImageDraw.Draw(image)
    kind = spec['kind']
    thickness = max(1, int(round(dpi / 150)))
    left, right = _px(12.0, dpi), width - _px(12.0, dpi)

    if kind == 'ruled':
        for y in rules['line_centers_px']:
            draw.line((left, y, right, y), fill=RULE_RGB, width=thickness)
    elif kind == 'grid':
        for y in rules['line_centers_px']:
            draw.line((left, y, right, y), fill=RULE_RGB, width=thickness)
        x = left
        while x <= right:
            draw.line((x, rules['first_line_px'], x, rules['line_centers_px'][-1]),
                      fill=RULE_RGB, width=thickness)
            x += rules['line_spacing_px']
    elif kind == 'dots':
        radius = max(1, thickness)
        for y in rules['line_centers_px']:
            x = left
            while x <= right:
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=RULE_RGB)
                x += rules['line_spacing_px']

    if rules['margin_x_px'] is not None:
        margin_x = rules['margin_x_px']
        draw.line((margin_x, 0, margin_x, height), fill=MARGIN_RGB, width=thickness)
    return image


# --- your own pages ---------------------------------------------------------

def imported_dir(name):
    return USER_PAPERS_DIR / name


def import_page(source, name, dpi=DPI):
    """Find the rules in a page once, and cache the page and its geometry."""
    image = paperlib.load_page(Path(source), dpi)
    rules = paperlib.detect_rules(image)
    if not rules['line_spacing_px']:
        raise ValueError(
            f'No ruled lines found in {source}.\n'
            f'{paperlib.describe(rules)}\n'
            'Import a page with visible rules, or use a preset such as college.')
    directory = imported_dir(name)
    directory.mkdir(parents=True, exist_ok=True)
    image.save(directory / 'page.png')
    (directory / 'geometry.json').write_text(json.dumps(rules, indent=2), encoding='utf-8')
    return directory


def imported_names():
    if not USER_PAPERS_DIR.is_dir():
        return []
    return sorted(p.name for p in USER_PAPERS_DIR.iterdir()
                  if (p / 'geometry.json').is_file() and (p / 'page.png').is_file())


def available():
    """Every paper you can name, presets first."""
    return list(PRESETS) + imported_names()


# --- the one way anything gets paper ----------------------------------------

def load(name_or_path, dpi=DPI):
    """(image, rules) for a preset name, an imported name, or a file path.

    A preset and an imported page come back in the same form, so nothing
    downstream has to know which it was given.
    """
    key = str(name_or_path)
    if key in PRESETS:
        return draw_preset(key, dpi), preset_geometry(key, dpi)
    directory = imported_dir(key)
    if (directory / 'geometry.json').is_file():
        rules = json.loads((directory / 'geometry.json').read_text(encoding='utf-8'))
        rules['size_px'] = tuple(rules['size_px'])
        return Image.open(directory / 'page.png').convert('RGB'), rules
    path = Path(key)
    if path.is_file():
        image = paperlib.load_page(path, dpi)
        return image, paperlib.detect_rules(image)
    raise FileNotFoundError(
        f'No paper called {key!r}, and no file at that path.\n'
        f'Available: {", ".join(available())}\n'
        'Import your own with:  python3 papers.py import PAGE.pdf --name NAME')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='show every paper you can write on')
    importer = sub.add_parser('import', help='add one of your own pages')
    importer.add_argument('source', help='a ruled page, as PDF or image')
    importer.add_argument('--name', required=True, help='what to call it afterwards')
    preview = sub.add_parser('preview', help='save a preset as a PNG, to look at it')
    preview.add_argument('name', choices=list(PRESETS))
    preview.add_argument('output')
    args = ap.parse_args()

    if args.command == 'list':
        for name in PRESETS:
            print(f'  {name:<14} {PRESETS[name]["display"]}')
        for name in imported_names():
            rules = json.loads((imported_dir(name) / 'geometry.json').read_text())
            print(f'  {name:<14} yours, {rules["line_count"]} rules '
                  f'at {rules["line_spacing_px"]:.1f}px')
    elif args.command == 'import':
        try:
            print(f'Imported to {import_page(args.source, args.name)}')
        except (ValueError, RuntimeError, FileNotFoundError) as error:
            sys.exit(str(error))
    else:
        draw_preset(args.name).save(args.output)
        print(f'Wrote {args.output}')


if __name__ == '__main__':
    main()
