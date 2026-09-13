"""The writing has to sit *on* the ruled lines, not merely at their pitch."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import handwrite

SIZES = ((22, 40), (30, 44), (18, 32), (26, 50))


def first_baseline(font_path, font_size, line_height):
    """Where the first baseline lands inside the page, in CSS pixels."""
    pad = handwrite.first_rule_offset(font_path, font_size, line_height)
    asc, desc, upem = handwrite.font_vmetrics(str(font_path))
    content_h = font_size * (asc + desc) / upem
    return pad + (line_height - content_h) / 2.0 + font_size * asc / upem


class RuledPaperPhaseTests(unittest.TestCase):
    def test_first_baseline_lands_on_a_rule_for_every_bundled_font(self):
        for name, spec in handwrite.FONTS.items():
            path = handwrite.FONT_DIR / spec['regular']
            for font_size, line_height in SIZES:
                with self.subTest(font=name, size=font_size, leading=line_height):
                    baseline = first_baseline(path, font_size, line_height)
                    # Rule centres sit at k * line_height - 0.5, because the
                    # background paints its rule in the band's last pixel.
                    off = (baseline + 0.5) % line_height
                    self.assertLess(min(off, line_height - off), 1e-6,
                                    f'baseline {baseline} is off the rule grid')

    def test_offset_stays_within_one_line(self):
        """A correction bigger than the spacing would silently eat a line."""
        for name, spec in handwrite.FONTS.items():
            path = handwrite.FONT_DIR / spec['regular']
            for font_size, line_height in SIZES:
                with self.subTest(font=name, size=font_size, leading=line_height):
                    pad = handwrite.first_rule_offset(path, font_size, line_height)
                    self.assertGreaterEqual(pad, 0)
                    self.assertLess(pad, line_height)

    def test_a_taller_font_needs_a_different_phase(self):
        """Guards against the correction being quietly hardcoded."""
        offsets = {name: handwrite.first_rule_offset(
            handwrite.FONT_DIR / spec['regular'], 22, 40)
            for name, spec in handwrite.FONTS.items()}
        self.assertGreater(len(set(round(v, 3) for v in offsets.values())), 1, offsets)


if __name__ == '__main__':
    unittest.main()
