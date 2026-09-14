"""Presets describe their own geometry, so the drawn page and the numbers the
renderer uses have to agree — that is what these check."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handwriting import handwrite
from handwriting import paper as paperlib
from handwriting import papers

FONT = handwrite.FONT_DIR / 'Kalam-Regular.ttf'


class PresetGeometryTests(unittest.TestCase):
    def test_every_preset_has_usable_geometry(self):
        for name in papers.PRESETS:
            with self.subTest(paper=name):
                rules = papers.preset_geometry(name)
                self.assertGreater(rules['line_spacing_px'], 0)
                self.assertGreater(rules['first_line_px'], 0)
                self.assertGreater(rules['line_count'], 10)
                self.assertTrue(0 < rules['line_spacing_frac'] < 1)
                self.assertTrue(0 < rules['first_line_frac'] < 1)
                self.assertEqual(rules['size_px'], (1275, 1650))

    def test_the_drawn_page_matches_the_geometry_it_declares(self):
        """Detecting rules back out of a drawn preset must recover what it said."""
        for name in ('college', 'ruled-wide', 'ruled-narrow'):
            with self.subTest(paper=name):
                declared = papers.preset_geometry(name)
                found = paperlib.detect_rules(papers.draw_preset(name))
                self.assertAlmostEqual(found['line_spacing_px'],
                                       declared['line_spacing_px'], delta=1.0)
                self.assertAlmostEqual(found['first_line_px'],
                                       declared['first_line_px'], delta=2.0)
                self.assertAlmostEqual(found['margin_x_px'],
                                       declared['margin_x_px'], delta=2.0)

    def test_a_blank_preset_draws_no_rules_but_still_sets_a_rhythm(self):
        rules = papers.preset_geometry('blank')
        self.assertGreater(rules['line_spacing_px'], 0)
        found = paperlib.detect_rules(papers.draw_preset('blank'))
        self.assertEqual(found['line_count'], 0)

    def test_real_world_spacings(self):
        """Wide 8.7mm, college 7.1mm, narrow 6.35mm — the actual standards."""
        for name, mm in (('ruled-wide', 8.7), ('college', 7.1), ('ruled-narrow', 6.35)):
            with self.subTest(paper=name):
                expected = mm / 25.4 * papers.DPI
                self.assertAlmostEqual(
                    papers.preset_geometry(name)['line_spacing_px'], expected, places=6)


class WritingLandsOnTheRulesTests(unittest.TestCase):
    def test_the_first_baseline_sits_on_the_first_rule_of_every_preset(self):
        for name in papers.PRESETS:
            with self.subTest(paper=name):
                layout, rules = handwrite.paper_layout(name, str(FONT), 19)
                self.assertIsNotNone(layout, f'{name} produced no layout')
                page_h_css = layout['page_h_in'] * 96
                first_rule = rules['first_line_frac'] * page_h_css
                asc, desc, upem = handwrite.font_vmetrics(str(FONT))
                content_h = 19 * (asc + desc) / upem
                baseline = (layout['pad_top']
                            + (layout['line_height'] - content_h) / 2.0
                            + 19 * asc / upem)
                self.assertAlmostEqual(baseline, first_rule, places=6)

    def test_line_height_is_not_rounded_to_a_whole_pixel(self):
        """Rounding walks the writing off the rules over a page."""
        layout, _ = handwrite.paper_layout('college', str(FONT), 19)
        self.assertNotEqual(layout['line_height'], round(layout['line_height']),
                            'college spacing is fractional; rounding it would drift')


class SelectionTests(unittest.TestCase):
    def test_a_preset_is_selected_by_name(self):
        image, rules = papers.load('college')
        self.assertEqual(image.size, (1275, 1650))
        self.assertEqual(rules['line_spacing_px'],
                         papers.preset_geometry('college')['line_spacing_px'])

    def test_a_file_path_still_works(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'page.png'
            papers.draw_preset('college').save(path)
            image, rules = papers.load(path)
            self.assertGreater(rules['line_count'], 10)

    def test_an_unknown_name_lists_what_is_available(self):
        with self.assertRaises(FileNotFoundError) as caught:
            papers.load('not-a-paper')
        message = str(caught.exception)
        self.assertIn('college', message)
        self.assertIn('handwrite-papers import', message)

    def test_an_imported_page_is_then_selectable_by_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'mine.png'
            papers.draw_preset('ruled-wide').save(source)
            with patch.object(papers, 'USER_PAPERS_DIR', root / 'papers'):
                papers.import_page(source, 'mine')
                self.assertIn('mine', papers.imported_names())
                self.assertIn('mine', papers.available())
                image, rules = papers.load('mine')
                # The same page comes back, geometry included, without re-detecting.
                self.assertEqual(image.size, (1275, 1650))
                self.assertAlmostEqual(
                    rules['line_spacing_px'],
                    papers.preset_geometry('ruled-wide')['line_spacing_px'], delta=1.0)

    def test_importing_a_page_with_no_rules_says_so(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'blank.png'
            papers.draw_preset('blank').save(source)
            with patch.object(papers, 'USER_PAPERS_DIR', root / 'papers'):
                with self.assertRaises(ValueError) as caught:
                    papers.import_page(source, 'nope')
        self.assertIn('No ruled lines', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
