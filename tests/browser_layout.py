"""Integration checks with the local Chromium installation: python3 tests/browser_layout.py."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
import clean
import handwrite

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
    browser.close()
print('Browser layout checks passed')
