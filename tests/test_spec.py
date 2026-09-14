"""A render is a pure function of a spec, so the spec has to say everything."""
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handwriting import hands
from handwriting.spec import DEFAULT_LINE_HEIGHT, SPEC_VERSION, RenderSpec


@contextmanager
def only_stock_hands():
    """Pin discovery, so a hand on the real machine cannot change a default."""
    with tempfile.TemporaryDirectory() as empty:
        environment = dict(os.environ)
        environment.pop('HANDWRITING_HANDS', None)
        with patch.object(hands, 'USER_HANDS_DIR', Path(empty)), \
             patch.object(hands, 'LEGACY_FONT_DIR', Path(empty)), \
             patch.dict('os.environ', environment, clear=True):
            yield


class DefaultsTests(unittest.TestCase):
    def test_content_is_the_only_required_field(self):
        with only_stock_hands():
            spec = RenderSpec(content='notes.txt')
            self.assertEqual(spec.hand, 'kalam')
            self.assertEqual(spec.font_variants(), {})
            self.assertEqual(spec.metrics(), (None, DEFAULT_LINE_HEIGHT))
            self.assertIsNone(spec.paper)

    def test_a_spec_without_content_is_rejected(self):
        with self.assertRaises(ValueError):
            RenderSpec(content='')

    def test_out_of_range_values_are_rejected(self):
        for bad in ({'font_size': 0}, {'line_height': -1}, {'math_scale': 0},
                    {'bracket_stroke_scale': 0}, {'version': 99}):
            with self.subTest(**bad):
                with self.assertRaises(ValueError):
                    RenderSpec(content='notes.txt', **bad)


class FontResolutionTests(unittest.TestCase):
    def test_explicit_fonts_win_over_the_named_hand(self):
        with only_stock_hands():
            spec = RenderSpec(content='n.txt', hand='caveat', fonts={'A': '/tmp/a.ttf'})
            self.assertEqual(spec.font_variants(), {'A': '/tmp/a.ttf'})

    def test_a_bundled_name_selects_that_font_and_no_variants(self):
        with only_stock_hands():
            spec = RenderSpec(content='n.txt', hand='caveat')
            self.assertEqual(spec.font_key(), 'caveat')
            self.assertEqual(spec.font_variants(), {})

    def test_an_unknown_hand_falls_back_to_a_usable_bundled_font(self):
        with only_stock_hands():
            self.assertEqual(RenderSpec(content='n.txt', hand='nope').font_key(), 'kalam')

    def test_sparse_variants_keep_their_letters(self):
        """A and C with no B must not slide C into B's slot."""
        with only_stock_hands():
            spec = RenderSpec(content='n.txt', fonts={'A': '/a.ttf', 'C': '/c.ttf'})
            variants = spec.font_variants()
            self.assertEqual(variants.get('A'), '/a.ttf')
            self.assertEqual(variants.get('C'), '/c.ttf')
            self.assertIsNone(variants.get('B'))

    def test_variant_letters_are_validated(self):
        with self.assertRaises(ValueError):
            RenderSpec(content='n.txt', fonts={'E': '/e.ttf'})
        with self.assertRaises(ValueError):
            RenderSpec(content='n.txt', fonts={'B': '/b.ttf'})   # no A

    def test_a_named_hand_supplies_its_own_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'mine').mkdir()
            for letter in 'AB':
                (root / 'mine' / f'{letter}.ttf').touch()
            (root / 'mine' / 'hand.json').write_text(
                json.dumps({'font_size': 31, 'line_height': 47}), encoding='utf-8')
            with patch.object(hands, 'USER_HANDS_DIR', root), \
                 patch.object(hands, 'LEGACY_FONT_DIR', root / 'none'), \
                 patch.dict('os.environ', {}, clear=True):
                spec = RenderSpec(content='n.txt', hand='mine')
                self.assertEqual(spec.metrics(), (31, 47))
                self.assertEqual(sorted(spec.font_variants()), ['A', 'B'])
                # An explicit value still wins over the hand's recommendation.
                self.assertEqual(spec.replace(font_size=18).metrics(), (18, 47))


class PersistenceTests(unittest.TestCase):
    def test_round_trip_through_json_preserves_every_field(self):
        with only_stock_hands():
            spec = RenderSpec(content='n.txt', hand='caveat', fonts={'A': '/a.ttf'},
                              paper='p.png', font_size=28, line_height=44, seed=9,
                              jitter=False, clean=True, hand_math=True,
                              hand_delims=False, math_scale=1.1,
                              bracket_stroke_scale=0.8)
            self.assertEqual(RenderSpec.from_dict(json.loads(spec.to_json())), spec)

    def test_saved_specs_reload(self):
        with tempfile.TemporaryDirectory() as directory, only_stock_hands():
            path = Path(directory) / 'nested' / 'render.json'
            spec = RenderSpec(content='n.txt', seed=4)
            spec.save(path)
            self.assertEqual(RenderSpec.load(path), spec)

    def test_a_stray_field_is_reported_rather_than_ignored(self):
        with self.assertRaises(ValueError) as caught:
            RenderSpec.from_dict({'content': 'n.txt', 'font_sze': 22})
        self.assertIn('font_sze', str(caught.exception))

    def test_a_future_spec_version_is_refused(self):
        with self.assertRaises(ValueError):
            RenderSpec.from_dict({'content': 'n.txt', 'version': SPEC_VERSION + 1})

    def test_replace_leaves_the_original_alone(self):
        with only_stock_hands():
            spec = RenderSpec(content='n.txt', seed=1)
            self.assertEqual(spec.replace(seed=2).seed, 2)
            self.assertEqual(spec.seed, 1)


if __name__ == '__main__':
    unittest.main()
