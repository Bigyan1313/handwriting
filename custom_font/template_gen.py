#!/usr/bin/env python3
"""
Generate a handwriting-sample template: a multi-page PDF with a grid of
boxes to write in, plus manifest.json recording each box's exact rectangle
(in inches, page-relative) so extraction can crop precisely regardless of
what resolution the filled-in export comes back at.

    python3 template_gen.py output/template.pdf output/manifest.json
    python3 template_gen.py output/template2.pdf output/manifest2.json --label "Set 2"
    python3 template_gen.py output/math.pdf output/math_manifest.json --set math
"""
import argparse
import html
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from charset import pages_for, safe_name

PAGE_W_IN = 8.5
PAGE_H_IN = 11.0

COLS = 6
CELL_IN = 1.10
GAP_IN = 0.10
MARGIN_LEFT_IN = 0.75
MARGIN_TOP_IN = 1.55

BASELINE_FRAC = 0.68   # fraction down from cell top where the baseline sits
XHEIGHT_FRAC = 0.40    # fraction down from cell top for the x-height guide

REG_SIZE_IN = 0.16
REG_INSET_IN = 0.28

TALL_CHARS = set("[]{}|()")   # get an extra "draw this tall" note


def grid_cells(entries):
    cells = []
    for i, (ch, note) in enumerate(entries):
        row, col = divmod(i, COLS)
        x = MARGIN_LEFT_IN + col * (CELL_IN + GAP_IN)
        y = MARGIN_TOP_IN + row * (CELL_IN + GAP_IN)
        cells.append({
            "char": ch,
            "note": note,
            "safe_name": safe_name(ch),
            "rect_in": [round(x, 4), round(y, 4), CELL_IN, CELL_IN],
            "baseline_frac": BASELINE_FRAC,
            "xheight_frac": XHEIGHT_FRAC,
        })
    return cells


def registration_marks():
    inset, s = REG_INSET_IN, REG_SIZE_IN
    return [
        [inset, inset, s, s],
        [PAGE_W_IN - inset - s, inset, s, s],
        [inset, PAGE_H_IN - inset - s, s, s],
        [PAGE_W_IN - inset - s, PAGE_H_IN - inset - s, s, s],
    ]


def build_manifest(set_name, label):
    pages = []
    for idx, (key, title, entries) in enumerate(pages_for(set_name)):
        pages.append({
            "name": key,
            "title": title,
            "page_index": idx,
            "cells": grid_cells(entries),
        })
    return {
        "page_size_in": [PAGE_W_IN, PAGE_H_IN],
        "baseline_frac": BASELINE_FRAC,
        "set": set_name,
        "label": label,
        "registration_marks_in": registration_marks(),
        "pages": pages,
    }


def cell_html(cell):
    x, y, w, h = cell["rect_in"]
    ch = html.escape(cell["char"])
    note = html.escape(cell["note"])
    note_html = f'<div class="note">{note}</div>' if note else ""
    tall = '<div class="tall">draw tall</div>' if cell["char"] in TALL_CHARS else ""
    baseline_y = h * cell["baseline_frac"]
    xheight_y = h * cell["xheight_frac"]
    return f'''
<div class="cell" style="left:{x}in; top:{y}in; width:{w}in; height:{h}in;">
  <div class="label">{ch}</div>
  {note_html}{tall}
  <div class="xline" style="top:{xheight_y}in;"></div>
  <div class="baseline" style="top:{baseline_y}in;"></div>
</div>'''


def reg_mark_html(rect):
    x, y, w, h = rect
    return f'<div class="regmark" style="left:{x}in; top:{y}in; width:{w}in; height:{h}in;"></div>'


def page_html(page, page_num, total_pages, label, set_name):
    cells = "\n".join(cell_html(c) for c in page["cells"])
    regs = "\n".join(reg_mark_html(r) for r in registration_marks())
    suffix = f" — {label}" if label else ""
    if set_name == "math":
        instructions = (
            "Write each symbol ONCE inside its box, sitting on the solid blue baseline. "
            "The gray symbol and its name in the corner tell you what to write. "
            "Brackets marked \"draw tall\" should fill the box top to bottom — they get "
            "stretched to fit around matrices. "
            "<b>Skip any symbol you never use</b> — blank boxes are fine, those just stay typeset."
        )
    else:
        instructions = (
            "Write each character ONCE inside its box, sitting on the solid blue baseline "
            "(letters with tails like g/y/p/q/j hang below it). Use a dark pen/pencil. "
            "Write it the way you normally would — this is a second version of each letter, "
            "so don't try to copy your first set exactly."
        )
    return f'''
<div class="page">
  <div class="header">
    <div class="title">Handwriting sample{suffix} — {page["title"]} ({page_num}/{total_pages})</div>
    <div class="instructions">{instructions}</div>
  </div>
  {regs}
  {cells}
</div>'''


def build_html(manifest):
    label, set_name = manifest["label"], manifest["set"]
    pages = "\n".join(
        page_html(p, i + 1, len(manifest["pages"]), label, set_name)
        for i, p in enumerate(manifest["pages"])
    )
    return f'''<!doctype html>
<html><head><meta charset="utf-8">
<style>
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{ font-family: "DejaVu Sans", Helvetica, Arial, sans-serif; }}

.page {{
  position: relative;
  width: {PAGE_W_IN}in;
  height: {PAGE_H_IN}in;
  break-after: page;
}}

.header {{ position: absolute; left: {MARGIN_LEFT_IN}in; top: 0.4in;
           width: {PAGE_W_IN - 2*MARGIN_LEFT_IN}in; }}
.title {{ font-size: 15px; font-weight: 700; color: #111; margin-bottom: 4px; }}
.instructions {{ font-size: 10px; color: #444; line-height: 1.45; }}

.cell {{ position: absolute; border: 1px dashed #bbb; border-radius: 4px; }}
.label {{ position: absolute; top: 1px; left: 5px; font-size: 13px; color: #aaa; }}
.note {{ position: absolute; top: 4px; right: 5px; font-size: 7.5px; color: #c4c4c4; }}
.tall {{ position: absolute; bottom: 2px; right: 5px; font-size: 7px; color: #d0a0a0; }}
.xline {{ position: absolute; left: 0; right: 0; border-top: 1px dashed #cfe0f0; }}
.baseline {{ position: absolute; left: 0; right: 0; border-top: 1.4px solid #8fb7e0; }}
.regmark {{ position: absolute; background: #e23a3a; }}

@page {{ size: Letter; margin: 0; }}
</style></head>
<body>
{pages}
</body></html>
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output_pdf")
    ap.add_argument("output_manifest")
    ap.add_argument("--set", choices=["alphabet", "math"], default="alphabet")
    ap.add_argument("--label", default="", help='e.g. "Set 2"')
    ap.add_argument("--keep-html", metavar="PATH")
    args = ap.parse_args()

    manifest = build_manifest(args.set, args.label)
    html_doc = build_html(manifest)

    html_path = Path(args.keep_html) if args.keep_html else Path("output/_template.html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_doc)
    Path(args.output_manifest).write_text(json.dumps(manifest, indent=2))

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=["--no-sandbox"])
        except Exception:
            browser = p.chromium.launch(args=["--no-sandbox"], channel="chrome")
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri())
        page.pdf(path=args.output_pdf, print_background=True, prefer_css_page_size=True)
        browser.close()

    n = sum(len(p["cells"]) for p in manifest["pages"])
    print(f"Wrote {args.output_pdf} ({len(manifest['pages'])} pages, {n} boxes) "
          f"and {args.output_manifest}")


if __name__ == "__main__":
    main()
