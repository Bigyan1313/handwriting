#!/usr/bin/env python3
"""
Given a filled-in template (PDF, exported from GoodNotes) and the
manifest.json from template_gen.py, crop out each written character,
isolate the ink from the printed guide lines, and save one tightly-cropped
PNG per glyph plus a meta.json recording where each glyph's baseline sits
(needed by build_font.py to align everything correctly).

Usage:
    python3 extract_glyphs.py filled.pdf manifest.json glyphs/
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

DPI = 200
INK_LUMA_THRESHOLD = 150   # pixels darker than this (0-255) count as ink
PAD_PX = 6


def rasterize_pdf(pdf_path: Path, dpi: int, out_dir: Path):
    if not shutil.which('pdftoppm'):
        try:
            import pymupdf
        except ImportError as exc:
            raise RuntimeError('Install Poppler or pip install pymupdf to read PDF samples') from exc
        pages = []
        with pymupdf.open(pdf_path) as doc:
            for i, page in enumerate(doc):
                path = out_dir / f'page-{i + 1:04d}.png'
                page.get_pixmap(dpi=dpi, alpha=False).save(path)
                pages.append(path)
        return pages
    prefix = out_dir / "page"
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
        check=True,
    )
    pages = sorted(out_dir.glob("page-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
    if not pages:
        # single-page PDFs sometimes come out without the numeric suffix
        pages = sorted(out_dir.glob("page*.png"))
    return pages


def luma(arr):
    # arr: HxWx3 uint8
    return 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]


def extract_cell(page_arr, rect_in, page_w_in, page_h_in, dpi, baseline_frac):
    ph, pw = page_arr.shape[:2]
    x_in, y_in, w_in, h_in = rect_in
    x0 = int(round(x_in / page_w_in * pw))
    y0 = int(round(y_in / page_h_in * ph))
    x1 = int(round((x_in + w_in) / page_w_in * pw))
    y1 = int(round((y_in + h_in) / page_h_in * ph))
    # shrink slightly inward so we never pick up the dashed cell border itself
    inset = max(2, int(0.02 * dpi))
    x0i, y0i, x1i, y1i = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    crop = page_arr[y0i:y1i, x0i:x1i]

    l = luma(crop)
    ink_mask = l < INK_LUMA_THRESHOLD

    baseline_px_in_crop = (y1i - y0i) * baseline_frac - 0  # baseline within the inset crop

    if not ink_mask.any():
        return None, baseline_px_in_crop, (y1i - y0i)

    ys, xs = np.where(ink_mask)
    top, bottom = ys.min(), ys.max()
    left, right = xs.min(), xs.max()

    top_p = max(0, top - PAD_PX)
    bottom_p = min(crop.shape[0] - 1, bottom + PAD_PX)
    left_p = max(0, left - PAD_PX)
    right_p = min(crop.shape[1] - 1, right + PAD_PX)

    sub_mask = ink_mask[top_p:bottom_p + 1, left_p:right_p + 1]
    glyph_img = np.where(sub_mask, 0, 255).astype(np.uint8)  # black ink on white

    baseline_in_glyph = baseline_px_in_crop - top_p
    cell_h_after_inset = y1i - y0i

    return glyph_img, baseline_in_glyph, cell_h_after_inset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("filled_pdf")
    ap.add_argument("manifest")
    ap.add_argument("glyphs_dir")
    ap.add_argument('--variant', choices=['A', 'B', 'C', 'D'], help='select sample from a multi-variant template')
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    if any('variant' in c for p in manifest['pages'] for c in p['cells']) and not args.variant:
        ap.error('this template contains multiple samples; select --variant A or --variant B')
    page_w_in, page_h_in = manifest["page_size_in"]

    glyphs_dir = Path(args.glyphs_dir)
    glyphs_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        page_images = rasterize_pdf(Path(args.filled_pdf), DPI, tmp)

        if len(page_images) < len(manifest["pages"]):
            print(
                f"WARNING: filled PDF has {len(page_images)} page(s) but manifest expects "
                f"{len(manifest['pages'])}. Extra character pages will be skipped.",
                file=sys.stderr,
            )

        meta = {}
        missing = []
        for page_meta, img_path in zip(manifest["pages"], page_images):
            page_img = np.array(Image.open(img_path).convert("RGB"))
            for cell in page_meta["cells"]:
                if cell.get('variant') and cell['variant'] != args.variant:
                    continue
                glyph_img, baseline_in_glyph, cell_h = extract_cell(
                    page_img, cell["rect_in"], page_w_in, page_h_in, DPI,
                    cell["baseline_frac"],
                )
                name = cell["safe_name"]
                if glyph_img is None:
                    missing.append(cell["char"])
                    continue
                out_path = glyphs_dir / f"{name}.png"
                Image.fromarray(glyph_img).save(out_path)
                meta[name] = {
                    "char": cell["char"],
                    "baseline_px": float(baseline_in_glyph),
                    "cell_h_px": float(cell_h),
                    "width_px": int(glyph_img.shape[1]),
                    "height_px": int(glyph_img.shape[0]),
                }

        (glyphs_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    print(f"Extracted {len(meta)} glyph(s) to {glyphs_dir}")
    if missing:
        print(f"Blank / not found ({len(missing)}): {''.join(missing)}", file=sys.stderr)


if __name__ == "__main__":
    main()
