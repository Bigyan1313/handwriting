import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'custom_font'))
from stroke_profiles import thin, bracket_profile, arrow_profile, distance_to_background

ROOT = Path(__file__).resolve().parents[1] / 'custom_font'

class StrokeProfileTests(unittest.TestCase):
    @unittest.skipUnless(all((ROOT/f'brackets_{variant}'/f'u{ord(char):04X}.png').exists()
                            for variant in 'AB' for char in '[]'),
                         'requires local handwriting bracket samples')
    def test_samples_are_distinct_connected_paths(self):
        for char in '[]':
            a = bracket_profile(ROOT/'brackets_A'/f'u{ord(char):04X}.png')
            b = bracket_profile(ROOT/'brackets_B'/f'u{ord(char):04X}.png')
            self.assertNotEqual(a['points'], b['points'])
            for p in (a,b):
                self.assertLess(p['points'][0][1], p['points'][-1][1])
                self.assertTrue(0 < p['capHeight'] < p['height']/2)
                self.assertTrue(all(0 <= x < p['width'] and 0 <= y < p['height'] for x,y in p['points']))

    @unittest.skipUnless(all((ROOT/folder/'u2192.png').exists()
                            for folder in ('glyphs_math', 'glyphs_math2')),
                         'requires local handwriting arrow samples')
    def test_arrows_keep_both_head_branches(self):
        for folder in ('glyphs_math','glyphs_math2'):
            p = arrow_profile(ROOT/folder/'u2192.png')
            self.assertEqual(len(p['head']),2)
            self.assertEqual(p['shaft'][-1],p['head'][0][0])
            self.assertEqual(p['shaft'][-1],p['head'][1][0])
            self.assertGreater(p['shaft'][-1][0] - p['shaft'][0][0], p['width'] * .5)

    def test_thinning_and_pen_measurement(self):
        mask=np.zeros((30,30),dtype=bool);mask[5:25,12:17]=True
        skeleton=thin(mask);distance=distance_to_background(mask)
        self.assertTrue(skeleton.any())
        self.assertLess(skeleton.sum(),mask.sum())
        widths=2*distance[skeleton]-1
        self.assertAlmostEqual(float(np.median(widths)),5,delta=1)

if __name__ == '__main__':unittest.main()
