"""Create the visual acceptance PDF for brackets, symbols, and vector accents."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from pypdf import PdfReader, PdfWriter
from handwriting import clean
from handwriting import handwrite

matrix = lambda rows: r'\begin{bmatrix}' + r'\\'.join(['1&2'] * rows) + r'\end{bmatrix}'
fonts = handwrite.HERE / 'custom_font/output'
output = handwrite.HERE / 'output/handwriting_comparison.pdf'
with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    try:
        browser = p.chromium.launch(args=['--no-sandbox'])
    except Exception:
        browser = p.chromium.launch(channel='chrome', args=['--no-sandbox'])
    writer = PdfWriter()
    for size in (24, 30, 36):
        text = f'Problem 1 — Pen weight at {size}px\nTwo, three, and four rows:\n$$' + r'\quad'.join(matrix(n) for n in (2,3,4)) + r'''$$
Letters and Greek symbols: x X u μ β B. Missing sample: #.
$$x_1+u^2+\mu+\beta+B$$
Your vector arrows:
$$\vec{x}_1+\vec u+\vec{AB}+\overrightarrow{AB}$$
Different accent retained:
$$\hat{x}+\vec u$$
'''
        html = handwrite.build_html(clean.parse_blocks(text, grouped=True), 'kalam', 7, False,
            custom_font_path=str(fonts/'BigyanHand-A.ttf'), custom_font_b_path=str(fonts/'BigyanHand-B.ttf'),
            custom_font_c_path=str(fonts/'BigyanHand-C.ttf'), custom_font_d_path=str(fonts/'BigyanHand-D.ttf'),
            font_size=size, line_height=44, hand_math=True)
        path = Path(tmp)/f'{size}.html';path.write_text(html)
        page=browser.new_page();page.goto(path.as_uri());page.wait_for_function('window.__renderDone === true')
        report=page.evaluate('window.__layoutReport')
        assert not report['warnings'], report['warnings']
        pdf=Path(tmp)/f'{size}.pdf';page.pdf(path=str(pdf),print_background=True,prefer_css_page_size=True)
        writer.append(str(pdf));page.close()
    browser.close()
    writer.write(output)
print(output)
