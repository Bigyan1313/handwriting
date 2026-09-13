#!/usr/bin/env python3
"""
Generate a focused 1-page write-in template specifically for square brackets:
    - 2 samples of '[' (left bracket)
    - 2 samples of ']' (right bracket)
Includes square guide markers to encourage crisp 90° corners.

Usage:
    python3 bracket_template_gen.py [output_pdf] [manifest_json]
"""
import html
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
DEFAULT_PDF = HERE / "output" / "template_brackets.pdf"
DEFAULT_MANIFEST = HERE / "output" / "manifest_brackets.json"

PAGE_W_IN = 8.5
PAGE_H_IN = 11.0

# 2 rows x 2 cols of large, generous boxes for drawing brackets
CELL_W_IN = 2.2
CELL_H_IN = 3.0
GAP_X_IN = 1.2
GAP_Y_IN = 0.8
MARGIN_LEFT_IN = 1.45
MARGIN_TOP_IN = 2.2

REG_SIZE_IN = 0.16
REG_INSET_IN = 0.28


def registration_marks():
    inset, s = REG_INSET_IN, REG_SIZE_IN
    return [
        [inset, inset, s, s],
        [PAGE_W_IN - inset - s, inset, s, s],
        [inset, PAGE_H_IN - inset - s, s, s],
        [PAGE_W_IN - inset - s, PAGE_H_IN - inset - s, s, s],
    ]


ENTRIES = [
    {"char": "[", "label": "Sample 1: [", "note": "crisp 90° square corners", "key": "bracket_left_1", "safe_name": "u005B"},
    {"char": "]", "label": "Sample 1: ]", "note": "crisp 90° square corners", "key": "bracket_right_1", "safe_name": "u005D"},
    {"char": "[", "label": "Sample 2: [", "note": "crisp 90° square corners (variant)", "key": "bracket_left_2", "safe_name": "u005B_var2"},
    {"char": "]", "label": "Sample 2: ]", "note": "crisp 90° square corners (variant)", "key": "bracket_right_2", "safe_name": "u005D_var2"},
]


def build_manifest():
    cells = []
    for i, e in enumerate(ENTRIES):
        row, col = divmod(i, 2)
        x = MARGIN_LEFT_IN + col * (CELL_W_IN + GAP_X_IN)
        y = MARGIN_TOP_IN + row * (CELL_H_IN + GAP_Y_IN)
        cells.append({
            "char": e["char"],
            "label": e["label"],
            "note": e["note"],
            "key": e["key"],
            "safe_name": "u005B" if e["char"] == "[" else "u005D",
            "variant": "A" if i < 2 else "B",
            "rect_in": [round(x, 4), round(y, 4), CELL_W_IN, CELL_H_IN],
            "baseline_frac": 0.85,
            "top_frac": 0.15,
        })
    return {
        "page_size_in": [PAGE_W_IN, PAGE_H_IN],
        "set": "brackets",
        "label": "Matrix Brackets Redo",
        "registration_marks_in": registration_marks(),
        "pages": [{
            "name": "brackets",
            "title": "Matrix Brackets (Square Corners)",
            "page_index": 0,
            "cells": cells,
        }],
    }


def generate_html(manifest):
    page = manifest["pages"][0]
    cells_html = []
    for c in page["cells"]:
        x, y, w, h = c["rect_in"]
        ch = html.escape(c["char"])
        lbl = html.escape(c["label"])
        note = html.escape(c["note"])
        cells_html.append(f"""
<div class="cell" style="left:{x}in; top:{y}in; width:{w}in; height:{h}in;">
  <div class="cell-label">{lbl}</div>
  <div class="cell-note">{note}</div>
  <div class="bracket-ghost">{ch}</div>
  <div class="top-guide" style="top:{h * 0.15}in;"></div>
  <div class="base-guide" style="top:{h * 0.85}in;"></div>
</div>""")

    reg_html = "".join(
        f'<div class="reg" style="left:{rx}in; top:{ry}in; width:{rw}in; height:{rh}in;"></div>'
        for rx, ry, rw, rh in manifest["registration_marks_in"]
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{ size: 8.5in 11in; margin: 0; }}
body {{
  margin: 0; padding: 0;
  width: 8.5in; height: 11in;
  position: relative;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: #222;
  background: #fff;
}}
.header {{
  position: absolute;
  top: 0.8in;
  left: 1.45in;
  right: 1.45in;
  text-align: center;
}}
.header h1 {{ margin: 0 0 6px 0; font-size: 22px; color: #111; }}
.header p {{ margin: 0; font-size: 13px; color: #555; line-height: 1.4; }}
.header .tip {{ color: #b22222; font-weight: 600; margin-top: 4px; }}

.cell {{
  position: absolute;
  border: 1.5px solid #bbb;
  box-sizing: border-box;
  background: #fafafa;
}}
.cell-label {{
  position: absolute;
  top: 8px; left: 10px;
  font-size: 13px;
  font-weight: 700;
  color: #aaa;
}}
.cell-note {{
  position: absolute;
  bottom: 8px; left: 10px;
  font-size: 11px;
  color: #bbb;
}}
.bracket-ghost {{
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  font-size: 96px;
  color: rgba(200, 210, 230, 0.4);
  font-family: "Courier New", monospace;
  font-weight: 300;
  pointer-events: none;
}}
.top-guide {{
  position: absolute;
  left: 15px; right: 15px;
  border-top: 1px dashed #c0c0c0;
}}
.base-guide {{
  position: absolute;
  left: 15px; right: 15px;
  border-top: 1.5px solid #99bbee;
}}
.reg {{
  position: absolute;
  background: #e23a3a;
}}
</style>
</head>
<body>
<div class="header">
  <h1>Matrix Brackets — Square Corner Template</h1>
  <p>Fill in each box with a dark pen on your iPad/paper sitting on the blue baseline up to the dashed top guide.<br>
  <span class="tip">Tip: Draw crisp, straight 90° corners (not curled hooks) so matrices scale naturally!</span></p>
</div>
{"".join(cells_html)}
{reg_html}
</body>
</html>"""


def main():
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    manifest_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_MANIFEST

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))

    html_content = generate_html(manifest)
    temp_html = pdf_path.with_suffix(".html")
    temp_html.write_text(html_content)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=["--no-sandbox"])
        except Exception:
            browser = p.chromium.launch(args=["--no-sandbox"], channel="chrome")
        page = browser.new_page()
        page.goto(temp_html.resolve().as_uri())
        page.pdf(path=str(pdf_path), print_background=True, prefer_css_page_size=True)
        browser.close()

    temp_html.unlink(missing_ok=True)
    print(f"Generated bracket template: {pdf_path}")
    print(f"Generated manifest: {manifest_path}")


if __name__ == "__main__":
    main()
