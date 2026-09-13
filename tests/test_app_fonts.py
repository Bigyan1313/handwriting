import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class PersonalFontTests(unittest.TestCase):
    def test_public_checkout_defaults_to_stock_fonts(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(app, 'PERSONAL_FONT_DIR', Path(directory)):
                self.assertEqual(app.available_styles(), app.FONTS)
                with self.assertRaises(FileNotFoundError):
                    app.personal_font_options()

    def test_personal_variants_are_default_and_missing_variants_are_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for variant in 'ACD':
                (root / f'BigyanHand-{variant}.ttf').touch()
            with patch.object(app, 'PERSONAL_FONT_DIR', root):
                self.assertEqual(app.available_styles()[0], app.PERSONAL_STYLE)
                options = app.personal_font_options()
                self.assertEqual(options[1], str(root / 'BigyanHand-A.ttf'))
                self.assertNotIn('--custom-font-b', options)
                self.assertIn('--custom-font-c', options)
                self.assertIn('--custom-font-d', options)

    def test_original_single_font_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'BigyanHand.ttf'
            path.touch()
            self.assertEqual(app.personal_font_options(directory)[1], str(path))
