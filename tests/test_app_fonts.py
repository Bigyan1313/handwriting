import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hands


class PersonalFontTests(unittest.TestCase):
    def test_public_checkout_defaults_to_stock_fonts(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(hands, 'PERSONAL_FONT_DIR', Path(directory)):
                self.assertEqual(hands.available_styles(), hands.FONTS)
                with self.assertRaises(FileNotFoundError):
                    hands.personal_font_options()

    def test_personal_variants_are_default_and_missing_variants_are_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for variant in 'ACD':
                (root / f'BigyanHand-{variant}.ttf').touch()
            with patch.object(hands, 'PERSONAL_FONT_DIR', root):
                self.assertEqual(hands.available_styles()[0], hands.PERSONAL_STYLE)
                options = hands.personal_font_options()
                self.assertEqual(options[1], str(root / 'BigyanHand-A.ttf'))
                self.assertNotIn('--custom-font-b', options)
                self.assertIn('--custom-font-c', options)
                self.assertIn('--custom-font-d', options)

    def test_original_single_font_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'BigyanHand.ttf'
            path.touch()
            self.assertEqual(hands.personal_font_options(directory)[1], str(path))

    def test_imports_without_pulling_in_a_gui_toolkit(self):
        """The point of this module: no Tk anywhere in its import graph, so the
        style logic still works on a headless machine."""
        result = subprocess.run(
            [sys.executable, '-c', "import sys, hands; assert 'tkinter' not in sys.modules"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
