#!/usr/bin/env python3
"""TEST-ONLY: fabricate a filled-in template by drawing each character with
a normal system font onto the template raster, so the extract/vectorize/
build pipeline can be validated end-to-end before real handwriting exists.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DPI = 200

manifest = json.loads(Path("output/manifest.json").read_text())
page_w_in, page_h_in = manifest["page_size_in"]

font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)

pages_out = []
for i, page_meta in enumerate(manifest["pages"]):
    img_path = f"output/tpl_preview-{i+1}.png" if DPI == 100 else None
    # always rasterize fresh at DPI to keep things consistent
    img = Image.open(f"output/tpl_preview-{i+1}.png").convert("RGB")
    if img.size[0] < 100:
        raise SystemExit("run template preview first")
    pw, ph = img.size
    draw = ImageDraw.Draw(img)
    for cell in page_meta["cells"]:
        x_in, y_in, w_in, h_in = cell["rect_in"]
        x0 = x_in / page_w_in * pw
        y0 = y_in / page_h_in * ph
        baseline_y = y0 + h_in / page_h_in * ph * cell["baseline_frac"]
        cx = x0 + (w_in / page_w_in * pw) * 0.3
        draw.text((cx, baseline_y), cell["char"], font=font, fill=(10, 10, 10), anchor="ls")
    pages_out.append(img)

import subprocess
tmp_paths = []
for i, img in enumerate(pages_out):
    p = f"output/_synthfill_{i}.png"
    img.save(p)
    tmp_paths.append(p)
subprocess.run(["img2pdf", *tmp_paths, "-o", "output/filled_test.pdf"], check=True)
print("wrote output/filled_test.pdf")
