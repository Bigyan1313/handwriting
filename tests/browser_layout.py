"""Integration checks with the local Chromium installation: python3 tests/browser_layout.py."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from handwriting import clean
from handwriting import handwrite

with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
    try:
        browser = p.chromium.launch(args=['--no-sandbox'])
    except Exception:
        browser = p.chromium.launch(channel='chrome', args=['--no-sandbox'])
    page = browser.new_page()
    def render(text, seed=1, **options):
        path = Path(tmp) / 'test.html'
        path.write_text(handwrite.build_html(clean.parse_blocks(text, grouped=True), 'kalam', seed, True, **options))
        page.goto(path.as_uri())
        page.wait_for_function('window.__renderDone === true')
        return page.evaluate('window.__layoutReport')
    text = '\n'.join(f'Problem {i}\n' + ('This is a readable sentence with a few short words. ' * 15) + '\n$$x=2$$' for i in range(1,6))
    report = render(text)
    assert all(l['words'] <= 11 for l in report['lines'])
    assert {p['blankTopLines'] for p in report['pages']} <= {2,3,4}
    assert all(p['usedHeight'] <= p['capacity'] + 1 for p in report['pages'])
    assert all(l['top'] <= 1056 - 60 - 4*40 + 1 for l in report['lines'] if l['heading'])
    assert not report['warnings'], report['warnings']
    assert render(text) == report, 'seed must reproduce layout'
    assert render(text, seed=2) != report
    # Custom variants, a matrix chain, and supplied paper geometry.
    font = str(handwrite.HERE / 'custom_font/output/BigyanHand-A.ttf')
    if not Path(font).exists():
        font = str(handwrite.FONT_DIR / handwrite.FONTS['kalam']['regular'])
    chain = r'\xrightarrow{R_2-R_1}'.join([r'\begin{bmatrix}1&2\\3&4\end{bmatrix}'] * 4)
    result = render('Problem 1\n$$'+chain+'$$', custom_font_path=font, custom_font_b_path=font, custom_font_c_path=font, custom_font_d_path=font, hand_math=True)
    assert not result['warnings'], result['warnings']
    assert page.locator('.display-math-src').count() >= 2
    assert page.locator('.katex-error').count() == 0
    paper = dict(page_w_in=8.5,page_h_in=11,line_height=40,pad_top=12,pad_left=104,bg_b64='')
    result = render(text, paper=paper)
    assert all(p['usedHeight'] <= p['capacity']+1 for p in result['pages'])
    assert not result['warnings'], result['warnings']
    # Every source word survives pagination exactly once.
    actual = page.locator('.page .w').all_text_contents()
    assert actual.count('readable') == 75
    # Every block has to advance the page by a whole number of ruled lines, or
    # the writing walks off the rules further down. Adjacent vertical margins
    # collapse to the larger of the two rather than adding, so display-math
    # spacing is padding; this is what catches it if that regresses. Jitter is
    # off because its rotation changes an element's bounding box.
    maths = """Problem 1
Inline math like $A\\vec x$ and $\\mu_1$ sits in the prose.
$$\\begin{bmatrix}1&2\\\\3&4\\end{bmatrix}$$
$$\\begin{bmatrix}5&6\\\\7&8\\end{bmatrix}$$
$$\\begin{bmatrix}9&1\\\\2&3\\end{bmatrix}$$
A line after three equations, which is where drift shows up.
$$x=\\frac{-b\\pm\\sqrt{b^2-4ac}}{2a}$$
The last line of all.
"""
    path = Path(tmp) / 'grid.html'
    path.write_text(handwrite.build_html(clean.parse_blocks(maths, grouped=True),
                                         'kalam', 1, False))
    page.goto(path.as_uri())
    page.wait_for_function('window.__renderDone === true')
    off_grid = page.evaluate("""() => {
      const LH = parseFloat(getComputedStyle(document.documentElement)
                   .getPropertyValue('--line-height'));
      const bad = [];
      document.querySelectorAll('.page').forEach(pageEl => {
        const style = getComputedStyle(pageEl);
        const origin = pageEl.getBoundingClientRect().top + parseFloat(style.paddingTop);
        pageEl.querySelectorAll('.hand-line, .display-math-src').forEach(el => {
          const rules = (el.getBoundingClientRect().top - origin) / LH;
          if (Math.abs(rules - Math.round(rules)) > 0.02) {
            bad.push({rules: +rules.toFixed(3), what: el.className.split(' ')[0],
                      text: (el.textContent || '').trim().slice(0, 30)});
          }
        });
      });
      return bad;
    }""")
    assert not off_grid, f'blocks not on the ruled grid: {off_grid}'
    browser.close()

# Renderer keeps one Chromium across renders. Starting Playwright and launching
# the browser costs about half a second, which a process rendering once pays in
# full; anything re-rendering in response to an edit should not.
from handwriting.handwrite import Renderer
from handwriting.spec import RenderSpec

with tempfile.TemporaryDirectory() as tmp, Renderer() as renderer:
    inside = renderer._browser
    spec = RenderSpec(content=str(Path(__file__).resolve().parents[1] / 'example_input.txt'))
    first = renderer.render(spec, str(Path(tmp) / 'a.pdf'))
    second = renderer.render(spec, str(Path(tmp) / 'b.pdf'))
    third = renderer.render(spec.replace(seed=2), str(Path(tmp) / 'c.pdf'))
    assert renderer._browser is inside, 'the browser was relaunched between renders'
    assert first == second, 'the same spec rendered differently on reuse'
    assert third != second, 'a different seed should lay out differently'
    for name in ('a.pdf', 'b.pdf', 'c.pdf'):
        assert (Path(tmp) / name).stat().st_size > 1000, f'{name} looks empty'
print('Browser layout checks passed')
