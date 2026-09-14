"""Reading a supplied ruled page must not need a system package installed."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

import paper

DPI = 150
PAGE_W, PAGE_H = 1275, 1650      # 8.5 x 11 inches at 150 dpi
RULE_SPACING, FIRST_RULE, MARGIN_X = 60, 180, 150


def ruled_page(path, fmt=None):
    """A page with known rule geometry, so detection can be checked against it."""
    image = Image.new('RGB', (PAGE_W, PAGE_H), (252, 250, 244))
    draw = ImageDraw.Draw(image)
    for y in range(FIRST_RULE, PAGE_H - 100, RULE_SPACING):
        draw.line((60, y, PAGE_W - 60, y), fill=(150, 175, 215), width=2)
    draw.line((MARGIN_X, 40, MARGIN_X, PAGE_H - 40), fill=(214, 120, 120), width=2)
    image.save(path, fmt, resolution=DPI) if fmt else image.save(path)
    return path


class ImagePageTests(unittest.TestCase):
    def test_an_image_page_needs_no_pdf_reader_at_all(self):
        with tempfile.TemporaryDirectory() as directory:
            path = ruled_page(Path(directory) / 'page.png')
            with patch.object(paper, '_pymupdf', lambda: None), \
                 patch('shutil.which', lambda name: None):
                image = paper.load_page(path)
            self.assertEqual(image.size, (PAGE_W, PAGE_H))
            self.assertIsNone(paper.page_size_in(path))


class PdfPageTests(unittest.TestCase):
    def test_a_pdf_page_rasterizes_without_poppler(self):
        with tempfile.TemporaryDirectory() as directory:
            path = ruled_page(Path(directory) / 'page.pdf', 'PDF')
            # No Poppler on PATH, exactly as on a machine that never had it.
            with patch('shutil.which', lambda name: None):
                image = paper.load_page(path)
                width, height = paper.page_size_in(path)
            self.assertGreater(image.size[0], 100)
            self.assertAlmostEqual(width, 8.5, places=1)
            self.assertAlmostEqual(height, 11.0, places=1)

    def test_rules_are_found_in_a_pdf_page(self):
        with tempfile.TemporaryDirectory() as directory:
            path = ruled_page(Path(directory) / 'page.pdf', 'PDF')
            with patch('shutil.which', lambda name: None):
                rules = paper.detect_rules(paper.load_page(path))
            self.assertGreater(rules['line_count'], 15)
            # Geometry comes back as page fractions, so it survives the dpi.
            self.assertAlmostEqual(rules['line_spacing_frac'],
                                   RULE_SPACING / PAGE_H, places=2)
            self.assertAlmostEqual(rules['first_line_frac'],
                                   FIRST_RULE / PAGE_H, places=2)
            self.assertAlmostEqual(rules['margin_x_frac'],
                                   MARGIN_X / PAGE_W, places=2)

    def test_with_no_reader_at_all_it_says_what_to_install(self):
        with tempfile.TemporaryDirectory() as directory:
            path = ruled_page(Path(directory) / 'page.pdf', 'PDF')
            with patch.object(paper, '_pymupdf', lambda: None), \
                 patch('shutil.which', lambda name: None):
                with self.assertRaises(RuntimeError) as caught:
                    paper.load_page(path)
            message = str(caught.exception)
            self.assertIn('pip install pymupdf', message)
            self.assertIn('Poppler', message)

    def test_an_unreadable_page_size_is_not_fatal(self):
        """Callers fall back to Letter, so this returns None rather than raising."""
        with tempfile.TemporaryDirectory() as directory:
            path = ruled_page(Path(directory) / 'page.pdf', 'PDF')
            with patch.object(paper, '_pymupdf', lambda: None), \
                 patch('shutil.which', lambda name: None):
                self.assertIsNone(paper.page_size_in(path))


if __name__ == '__main__':
    unittest.main()
