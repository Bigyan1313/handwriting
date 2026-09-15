import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hands


@contextmanager
def isolated_hands(user=None, legacy=None, extra=None):
    """Pin every search root, so discovery never depends on the real machine."""
    with tempfile.TemporaryDirectory() as empty:
        environment = dict(os.environ)
        environment.pop('HANDWRITING_HANDS', None)
        if extra:
            environment['HANDWRITING_HANDS'] = str(extra)
        with patch.object(hands, 'USER_HANDS_DIR', Path(user or empty)), \
             patch.object(hands, 'LEGACY_FONT_DIR', Path(legacy or empty)), \
             patch.dict('os.environ', environment, clear=True):
            yield


def make_hand(root, name, variants='A', metadata=None):
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    for letter in variants:
        (directory / f'{letter}.ttf').touch()
    if metadata is not None:
        (directory / 'hand.json').write_text(json.dumps(metadata), encoding='utf-8')
    return directory


class StockHandTests(unittest.TestCase):
    def test_public_checkout_offers_only_the_bundled_fonts(self):
        with isolated_hands():
            self.assertEqual(hands.available_styles(), hands.FONTS)
            self.assertEqual([h.name for h in hands.available_hands()], list(hands.FONTS))

    def test_stock_hands_render_with_the_font_flag(self):
        with isolated_hands():
            self.assertEqual(hands.find_hand('kalam').options, ('--font', 'kalam'))
            self.assertFalse(hands.find_hand('kalam').personal)


class PersonalHandTests(unittest.TestCase):
    def test_personal_hands_come_first_so_one_is_the_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_hand(root, 'my-hand', 'AB')
            with isolated_hands(user=root):
                self.assertEqual(hands.available_styles()[0], 'my-hand')
                self.assertTrue(hands.find_hand('my-hand').personal)

    def test_missing_variants_are_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_hand(root, 'my-hand', 'ACD')
            with isolated_hands(user=root):
                options = hands.find_hand('my-hand').options
                self.assertIn('--custom-font-c', options)
                self.assertIn('--custom-font-d', options)
                self.assertNotIn('--custom-font-b', options)

    def test_hand_json_sets_display_name_and_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_hand(root, 'neat', 'A',
                      {'display': 'My neat hand', 'font_size': 26, 'line_height': 38})
            with isolated_hands(user=root):
                hand = hands.find_hand('My neat hand')
                self.assertIsNotNone(hand)
                self.assertEqual(hand.name, 'neat')
                self.assertEqual(hand.options[3], '26')
                self.assertEqual(hand.options[5], '38')

    def test_several_hands_are_all_offered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('first', 'second', 'third'):
                make_hand(root, name, 'AB')
            with isolated_hands(user=root):
                styles = hands.available_styles()
                self.assertEqual(styles[:3], ('first', 'second', 'third'))
                self.assertEqual(styles[3:], hands.FONTS)

    def test_a_directory_without_a_font_is_not_a_hand(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'empty').mkdir()
            with isolated_hands(user=root):
                self.assertEqual(hands.available_styles(), hands.FONTS)

    def test_env_var_hands_are_found_before_the_user_directory(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            make_hand(Path(a), 'from-env', 'A')
            make_hand(Path(b), 'from-home', 'A')
            with isolated_hands(user=Path(b), extra=Path(a)):
                self.assertEqual(hands.available_styles()[:2], ('from-env', 'from-home'))


class LegacyLayoutTests(unittest.TestCase):
    def test_original_bigyan_layout_still_works(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory)
            for variant in 'ACD':
                (legacy / f'BigyanHand-{variant}.ttf').touch()
            with isolated_hands(legacy=legacy):
                self.assertEqual(hands.available_styles()[0], hands.PERSONAL_STYLE)
                options = hands.personal_font_options()
                self.assertEqual(options[1], str(legacy / 'BigyanHand-A.ttf'))
                self.assertNotIn('--custom-font-b', options)
                self.assertIn('--custom-font-c', options)

    def test_single_unsuffixed_font_is_treated_as_variant_a(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'BigyanHand.ttf'
            path.touch()
            self.assertEqual(hands.personal_font_options(directory)[1], str(path))

    def test_variant_a_wins_over_the_unsuffixed_font(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'BigyanHand.ttf').touch()
            (root / 'BigyanHand-A.ttf').touch()
            self.assertEqual(hands.personal_font_options(root)[1],
                             str(root / 'BigyanHand-A.ttf'))

    def test_a_directory_with_no_font_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                hands.personal_font_options(directory)


class HeadlessTests(unittest.TestCase):
    def test_imports_without_pulling_in_a_gui_toolkit(self):
        """The point of this module: no Tk anywhere in its import graph, so the
        style logic still works on a headless machine."""
        result = subprocess.run(
            [sys.executable, '-c', "import sys, hands; assert 'tkinter' not in sys.modules"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
