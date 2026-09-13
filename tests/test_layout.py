import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clean


class ParserTests(unittest.TestCase):
    def test_chain_preserves_nested_labels_and_delimiters(self):
        matrix = r'\left[\begin{array}{cc}1&2\\3&4\end{array}\right]'
        arrow = r'\xrightarrow{\frac{R_1}{2}}'
        tex = arrow.join([matrix] * 4)
        parts = clean.split_long_display_math(tex)
        self.assertEqual(len(parts), 2)
        self.assertEqual(''.join(parts), tex)
        for part in parts:
            self.assertEqual(part.count(r'\left'), part.count(r'\right'))
            self.assertEqual(part.count(r'\begin'), 2)

    def test_does_not_split_nested_equals(self):
        tex = r'\begin{aligned}a&=b\\c&=d\end{aligned}'
        self.assertEqual(clean.equation_parts(tex), [tex])

    def test_problem_groups(self):
        blocks = clean.parse_blocks('1.4 #1\nQuestion\n$$x=2$$\nAnswer\n\n1.4 #2\nNext', grouped=True)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(len(blocks[0][1]), 4)

    def test_extended_templates_fit_page(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'custom_font'))
        from template_gen import build_manifest
        for charset in ['alphabet', 'math']:
            for page in build_manifest(charset, 'Extra')['pages']:
                for cell in page['cells']:
                    x, y, w, h = cell['rect_in']
                    self.assertLessEqual(x+w, 8.5)
                    self.assertLessEqual(y+h, 11)

    def test_bracket_variants(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'custom_font'))
        from bracket_template_gen import build_manifest
        cells = build_manifest()['pages'][0]['cells']
        self.assertEqual([(c['char'], c['variant']) for c in cells], [('[', 'A'), (']', 'A'), ('[', 'B'), (']', 'B')])
        for c in cells:
            x,y,w,h = c['rect_in']
            self.assertLessEqual(x+w,8.5)
            self.assertLessEqual(y+h,11)


if __name__ == '__main__':
    unittest.main()
