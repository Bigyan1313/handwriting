"""Browser-level handwriting checks, including actual Chromium font selection.

Run from the project root: python3 tests/browser_handwriting.py
All generated HTML and deliberately incomplete test fonts live in a temp directory.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fontTools.ttLib import TTFont
from playwright.sync_api import sync_playwright

import clean
import handwrite

FONT_DIR = handwrite.HERE / 'custom_font' / 'output'
FONT_A = FONT_DIR / 'BigyanHand-A.ttf'
FONTS = [FONT_DIR / f'BigyanHand-{variant}.ttf' for variant in 'ABCD']
TARGETS = set('xXuμ βB'.replace(' ', ''))
MATRICES = [r'\begin{bmatrix}' + r'\\'.join(['1&2'] * rows) + r'\end{bmatrix}'
            for rows in (2, 3, 4)]
GLYPH_TEXT = r'''Problem 1
Hash # in prose; x X u μ β B; pasted 𝑥 𝒙 𝛍 µ 𝛃.
$$x+X+u+\mu+\beta+B$$
$$\vec x+\vec u+\vec{AB}+\overrightarrow{AB}$$
$$\vec{x}_1+\vec{u}^{2}+\mu_1+\beta^2$$
$$𝑥+𝒙+𝛍+µ+𝛃$$
'''


def postscript_name(path):
    with TTFont(path) as font:
        return font['name'].getDebugName(6)


def actual_fonts(page, selector):
    """Read browser-selected fonts, rather than trusting declared font-family."""
    session = page.context.new_cdp_session(page)
    try:
        session.send('DOM.enable')
        session.send('CSS.enable')
        root = session.send('DOM.getDocument')['root']['nodeId']
        ids = session.send('DOM.querySelectorAll', {'nodeId': root, 'selector': selector})['nodeIds']
        return [session.send('CSS.getPlatformFontsForNode', {'nodeId': node})['fonts'] for node in ids]
    finally:
        session.detach()


def main():
    with sync_playwright() as p, tempfile.TemporaryDirectory() as temporary:
        tmp = Path(temporary)
        try:
            browser = p.chromium.launch(args=['--no-sandbox'])
        except Exception:
            browser = p.chromium.launch(channel='chrome', args=['--no-sandbox'])
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        render_number = 0

        def render(text, fonts=FONTS, seed=7, **options):
            nonlocal render_number
            render_number += 1
            errors.clear()
            paths = dict(zip(['custom_font_path', 'custom_font_b_path',
                              'custom_font_c_path', 'custom_font_d_path'], map(str, fonts)))
            path = tmp / f'render-{render_number}.html'
            path.write_text(handwrite.build_html(clean.parse_blocks(text, grouped=True),
                'kalam', seed, True, hand_math=True, font_size=30, line_height=44,
                **paths, **options))
            page.goto(path.as_uri())
            page.wait_for_function('window.__renderDone === true')
            assert not errors, errors
            assert page.locator('.katex-error').count() == 0
            report = page.evaluate('window.__layoutReport')
            assert not report['warnings'], report['warnings']
            assert {entry['blankTopLines'] for entry in report['pages']} <= {2, 3, 4}
            assert all(entry['usedHeight'] <= entry['capacity'] + 1 for entry in report['pages'])
            return report

        def check_semantics():
            assert page.evaluate(r'''() => Array.from(document.querySelectorAll(
              '.math-src, .display-math-src')).every(root => {
                const expected=document.createElement('div');
                katex.render(root.dataset.tex, expected, {
                  displayMode:root.classList.contains('display-math-src'),throwOnError:false});
                return root.querySelector('.katex-mathml').innerHTML ===
                       expected.querySelector('.katex-mathml').innerHTML;
              })'''), 'handwriting replacement changed semantic MathML or original LaTeX'

        def check_fonts(expected_paths):
            # Include prose, plain math, vector bases, aliases, and sub/superscripts.
            glyphs = page.locator('.hand-glyph').evaluate_all('''nodes => nodes.filter(
              el => 'xXuμβB'.includes(el.textContent)).map((el, i) => {
                el.dataset.fontProbe = String(i);
                return {text:el.textContent, family:el.dataset.font, original:el.dataset.original};
              })''')
            assert TARGETS <= {glyph['text'] for glyph in glyphs}, glyphs
            allowed = {postscript_name(path) for path in expected_paths}
            for index, glyph in enumerate(glyphs):
                uses = actual_fonts(page, f'[data-font-probe="{index}"]')[0]
                assert uses and sum(font['glyphCount'] for font in uses) > 0, glyph
                assert all(font['postScriptName'] in allowed for font in uses), (glyph, uses)
            assert page.locator('.katex-accent .hand-glyph').count() >= 7
            aliases = {(glyph['original'], glyph['text']) for glyph in glyphs}
            assert ('µ', 'μ') in aliases and ('𝛍', 'μ') in aliases, aliases
            return glyphs

        for fonts in ([FONT_A], FONTS):
            report = render(GLYPH_TEXT, fonts=fonts)
            check_semantics()
            check_fonts(fonts)
            fallbacks = report['handwriting']['fallbacks']
            assert any(item['character'] == '#' for item in fallbacks), fallbacks
            assert not any(item['character'] in TARGETS for item in fallbacks), fallbacks
            assert all({'character', 'codepoint', 'context', 'reason'} <= item.keys()
                       for item in fallbacks)
            assert page.locator('.hand-vector-arrow').count() == 6
            assert page.locator('.hand-vector-arrow path').evaluate_all("nodes=>nodes.every(n=>getComputedStyle(n).stroke !== 'none' && getComputedStyle(n).fill === 'none')")
            # Glyph choices and geometry should be repeatable under the same seed.
            page.locator('[data-font-probe]').evaluate_all("nodes => nodes.forEach(n => n.removeAttribute('data-font-probe'))")
            snapshot = page.locator('.page').evaluate_all('(nodes) => nodes.map(n => n.outerHTML)')
            again = render(GLYPH_TEXT, fonts=fonts)
            assert again == report, 'same seed changed the layout or handwriting report'
            assert page.locator('.page').evaluate_all('(nodes) => nodes.map(n => n.outerHTML)') == snapshot

        # Force different coverage per font. A font claiming a family is not evidence
        # that it contains a character: verify Chromium never selects this sparse B.
        sparse = tmp / 'Sparse-B.ttf'
        with TTFont(FONTS[1]) as font:
            for table in font['cmap'].tables:
                if table.isUnicode():
                    for character in TARGETS:
                        table.cmap.pop(ord(character), None)
            font.save(sparse)
        render(GLYPH_TEXT, fonts=[FONT_A, sparse])
        glyphs = check_fonts([FONT_A])
        assert all(glyph['family'] == 'HandwritingFont' for glyph in glyphs), glyphs

        matrix_text = 'Problem 1\n' + '\n'.join('$$' + matrix + '$$' for matrix in MATRICES)
        sizes = []
        for size in (24, 30, 36):
            # font_size is intentionally selected at the call site rather than scaling
            # the DOM after geometry has been measured.
            source = handwrite.build_html(clean.parse_blocks(matrix_text, grouped=True),
                'kalam', 7, False, custom_font_path=str(FONT_A),
                custom_font_b_path=str(FONTS[1]), hand_math=True,
                font_size=size, line_height=44)
            matrix_path = tmp / f'matrices-{size}.html'
            matrix_path.write_text(source)
            page.goto(matrix_path.as_uri())
            page.wait_for_function('window.__renderDone === true')
            assert not errors, errors
            brackets = page.locator('.hand-bracket').evaluate_all('''nodes => nodes.map(svg => ({
              stroke: Number(svg.getAttribute('stroke-width')),
              reference: Number(svg.dataset.referenceStroke),
              family:svg.dataset.sampleFamily,
              height:svg.getBoundingClientRect().height,
              width:svg.getBoundingClientRect().width,
              path:svg.querySelector('path').getAttribute('d')
            }))''')
            assert len(brackets) == 6, brackets
            assert page.locator('.hand-bracket path').evaluate_all("nodes=>nodes.every(n=>getComputedStyle(n).stroke !== 'none' && getComputedStyle(n).fill === 'none')")
            weights = [bracket['stroke'] for bracket in brackets]
            assert all(weight > 0 for weight in weights)
            assert max(weights) / min(weights) <= 1.10, brackets
            assert all(abs(bracket['stroke'] / bracket['reference'] - 1) <= .15
                       for bracket in brackets), brackets
            assert all(bracket['width'] > 0 and bracket['path'] for bracket in brackets)
            assert brackets[0]['height'] < brackets[2]['height'] < brackets[4]['height']
            assert all(abs(brackets[i]['stroke'] - brackets[i+1]['stroke']) < .001
                       for i in (0, 2, 4)), brackets
            sizes.append(weights[0])
            check_semantics()
        assert sizes[0] < sizes[1] < sizes[2], sizes

        nested = r'''Problem 1
$$\begin{bmatrix}\begin{bmatrix}1\\2\end{bmatrix}&x\\3&4\end{bmatrix}$$
$$\left[x\right]+\Bigl[u\Bigr]$$
'''
        report = render(nested)
        assert page.locator('.hand-bracket').count() == 8
        check_semantics()
        render(nested, hand_delims=False)
        assert page.locator('.hand-bracket').count() == 0
        render(matrix_text, fonts=[FONT_A])
        normal = page.locator('.hand-bracket').evaluate_all('nodes => nodes.map(n => Number(n.getAttribute("stroke-width")))')
        render(matrix_text, fonts=[FONT_A], bracket_stroke_scale=.8)
        thinner = page.locator('.hand-bracket').evaluate_all('nodes => nodes.map(n => Number(n.getAttribute("stroke-width")))')
        assert all(abs(after / before - .8) < .001 for before, after in zip(normal, thinner))
        browser.close()
    print('Browser handwriting checks passed (fonts, vectors, brackets, semantics, coverage, seed, and layout)')


if __name__ == '__main__':
    main()
