import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'custom_font'))
try:
    import potrace
except ImportError:
    potrace = None

@unittest.skipUnless(potrace, 'portable backend requires potracer')
class PortableTests(unittest.TestCase):
    def _sample(self, directory, char):
        from PIL import Image, ImageDraw
        from charset import safe_name
        key = safe_name(char)
        im = Image.new('L', (60, 80), 255)
        draw = ImageDraw.Draw(im)
        if char == '#':
            draw.line((20, 8, 14, 70), fill=0, width=4)
            draw.line((44, 8, 38, 70), fill=0, width=4)
            draw.line((6, 28, 53, 28), fill=0, width=4)
            draw.line((4, 49, 51, 49), fill=0, width=4)
        else:
            draw.line((8, 70, 28, 10, 48, 70), fill=0, width=4)
            draw.line((16, 47, 40, 47), fill=0, width=4)
        im.save(directory / (key + '.png'))
        return {key: {'char': char, 'dir': str(directory)}}, {key: {'below': 5}}

    def test_outline_preserves_hole_and_disconnected_dot(self):
        from PIL import Image, ImageDraw
        from portable_font import trace_glyph
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'glyph.png'
            im = Image.new('L', (60, 80), 255)
            draw = ImageDraw.Draw(im)
            draw.rectangle((10, 30, 45, 70), fill=0)
            draw.rectangle((18, 38, 37, 62), fill=255)
            draw.ellipse((20, 8, 26, 14), fill=0)
            im.save(path)
            glyph, width = trace_glyph(path, 4, 5)
            self.assertEqual(glyph.numberOfContours, 3)
            self.assertGreater(glyph.yMax, glyph.yMin)
            self.assertEqual(width, 310)

    def test_add_hash_preserves_existing_glyphs_and_metrics(self):
        from fontTools.ttLib import TTFont
        from portable_font import build
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            base, patched = tmp / 'base.ttf', tmp / 'patched.ttf'
            meta, placements = self._sample(tmp, 'A')
            build(meta, placements, lambda _: 4, base, 'Test Hand', 800, 200)
            source_bytes = base.read_bytes()
            with TTFont(base) as font:
                original_order = font.getGlyphOrder()
                originals = {name: font['glyf'][name].compile(font['glyf']) for name in original_order}
                metrics = dict(font['hmtx'].metrics)
            meta, placements = self._sample(tmp, '#')
            build(meta, placements, lambda _: 4, patched, 'Test Hand', 800, 200, base_font=base)
            with TTFont(patched) as font:
                self.assertEqual(font.getGlyphOrder()[:-1], original_order)
                self.assertEqual(font['maxp'].numGlyphs, len(original_order) + 1)
                for name in original_order:
                    self.assertEqual(font['glyf'][name].compile(font['glyf']), originals[name])
                    self.assertEqual(font['hmtx'][name], metrics[name])
                hash_name = font.getBestCmap()[ord('#')]
                self.assertGreater(font['glyf'][hash_name].numberOfContours, 0)
                self.assertGreater(font['hmtx'][hash_name][0], 0)
                for table in font['cmap'].tables:
                    if table.isUnicode() and hasattr(table, 'cmap'):
                        self.assertEqual(table.cmap[ord('#')], hash_name)
            self.assertEqual(base.read_bytes(), source_bytes)
            # Replacing the added character again must not append duplicate glyphs.
            build(meta, placements, lambda _: 3, patched, 'Test Hand', 800, 200, base_font=patched)
            with TTFont(patched) as font:
                self.assertEqual(len(font.getGlyphOrder()), len(original_order) + 1)
                self.assertEqual(font['hmtx'][font.getBestCmap()[ord('#')]][0], 250)

    def test_add_non_bmp_character_keeps_complete_cmap(self):
        from fontTools.ttLib import TTFont
        from portable_font import build
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            base, patched = tmp / 'base.ttf', tmp / 'patched.ttf'
            meta, placements = self._sample(tmp, 'A')
            build(meta, placements, lambda _: 4, base, 'Test Hand', 800, 200)
            meta, placements = self._sample(tmp, '\U0001d54f')
            build(meta, placements, lambda _: 4, patched, 'Test Hand', 800, 200, base_font=base)
            with TTFont(patched) as font:
                self.assertIn(ord('A'), font.getBestCmap())
                self.assertIn(0x1D54F, font.getBestCmap())
                self.assertTrue(any(table.format == 12 for table in font['cmap'].tables))


class DefaultBackendTests(unittest.TestCase):
    """Building a font must not need FontForge, or an interpreter chosen to
    match it. The portable backend is the default; FontForge is opt-in."""

    def _glyph_dir(self, root):
        from PIL import Image, ImageDraw
        from charset import safe_name
        directory = root / 'glyphs'
        directory.mkdir()
        meta = {}
        for char in 'aA':
            image = Image.new('L', (60, 80), 255)
            draw = ImageDraw.Draw(image)
            draw.line((8, 70, 28, 10, 48, 70), fill=0, width=4)
            draw.line((16, 47, 40, 47), fill=0, width=4)
            image.save(directory / (safe_name(char) + '.png'))
            meta[safe_name(char)] = {'char': char, 'height_px': 60}
        (directory / 'meta.json').write_text(json.dumps(meta))
        return directory

    def test_the_default_backend_is_portable(self):
        import build_font
        self.assertEqual(
            inspect.signature(build_font.build).parameters['backend'].default, 'portable')

    @unittest.skipUnless(potrace, 'portable backend requires potracer')
    def test_a_font_builds_with_no_fontforge_present(self):
        import build_font
        self.assertIsNone(build_font.fontforge,
                          'this check is only meaningful where FontForge is absent')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / 'Built.ttf'
            build_font.build([self._glyph_dir(root)], out, 'Built Hand', None, None)
            self.assertTrue(out.is_file())
            from fontTools.ttLib import TTFont
            with TTFont(out) as font:
                cmap = font.getBestCmap()
            self.assertIn(ord('a'), cmap)
            self.assertIn(ord('A'), cmap)


class SupplementalTemplateTests(unittest.TestCase):
    def test_hash_manifest_uses_canonical_names_and_separate_variants(self):
        from supplemental_template_gen import build_manifest
        manifest = build_manifest()
        self.assertEqual(len(manifest['pages']), 1)
        cells = manifest['pages'][0]['cells']
        self.assertEqual([cell['variant'] for cell in cells], ['A', 'B'])
        self.assertEqual([cell['safe_name'] for cell in cells], ['u0023', 'u0023'])
        self.assertEqual([cell['char'] for cell in cells], ['#', '#'])
        for cell in cells:
            x, y, w, h = cell['rect_in']
            self.assertTrue(0 < x < x + w < manifest['page_size_in'][0])
            self.assertTrue(0 < y < y + h < manifest['page_size_in'][1])
        left, right = (cell['rect_in'] for cell in cells)
        self.assertLess(left[0] + left[2], right[0])

    def test_hash_appends_to_future_alphabet_without_reordering(self):
        from charset import ALPHABET_PAGES, ALL_CHARS
        original = list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,;:!?'\"()-+=/")
        self.assertEqual(ALL_CHARS, original + ['#'])
        self.assertEqual(ALPHABET_PAGES[-1][-1][-1], '#')

if __name__ == '__main__':
    unittest.main()
