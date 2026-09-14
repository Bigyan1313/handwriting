"""
Read a ruled page (a PDF or image exported from GoodNotes, say) and work out
where its lines are, so text can be written onto them instead of onto the
generated ruled background.

Returns, in page-relative fractions (0..1) so the numbers survive whatever
resolution the page came in at:
    line_spacing   distance between ruled lines
    first_line     y of the first ruled line
    margin_x       x of the vertical margin rule, if there is one
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

PROBE_DPI = 150

NO_PDF_READER = (
    "Reading a PDF page needs PyMuPDF or Poppler.\n"
    "Install one with:  pip install pymupdf\n"
    "(or install Poppler so pdftoppm and pdfinfo are on your PATH),\n"
    "or supply the ruled page as a PNG or JPEG instead."
)


def _pymupdf():
    """PyMuPDF, under either of the names it has shipped as, or None."""
    for name in ("pymupdf", "fitz"):
        try:
            return __import__(name)
        except ImportError:
            continue
    return None


def _is_pdf(path: Path) -> bool:
    return Path(path).suffix.lower() == ".pdf"


def load_page(path: Path, dpi: int = PROBE_DPI) -> Image.Image:
    """Rasterize page 1 of a PDF, or open an image, as RGB.

    PyMuPDF is preferred over Poppler: it installs with pip, and using the same
    rasterizer everywhere keeps rule detection consistent from machine to
    machine rather than depending on which tool happens to be installed.
    """
    path = Path(path)
    if not _is_pdf(path):
        return Image.open(path).convert("RGB")

    fitz = _pymupdf()
    if fitz is not None:
        with fitz.open(path) as document:
            if not document.page_count:
                raise RuntimeError(f"{path} has no pages")
            pixmap = document[0].get_pixmap(dpi=dpi, alpha=False)
            return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

    if shutil.which("pdftoppm"):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "pg"
            subprocess.run(
                ["pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", "1",
                 str(path), str(prefix)],
                check=True, capture_output=True,
            )
            pages = sorted(Path(tmp).glob("pg*.png"))
            if not pages:
                raise RuntimeError(f"Could not rasterize {path}")
            return Image.open(pages[0]).convert("RGB")

    raise RuntimeError(NO_PDF_READER)


def page_size_in(path: Path):
    """(width, height) of a PDF page in inches, or None if it cannot be read.

    Callers fall back to Letter, so an unreadable size is not fatal.
    """
    path = Path(path)
    if not _is_pdf(path):
        return None

    fitz = _pymupdf()
    if fitz is not None:
        with fitz.open(path) as document:
            if not document.page_count:
                return None
            rect = document[0].rect
            return rect.width / 72.0, rect.height / 72.0

    if shutil.which("pdfinfo"):
        out = subprocess.run(["pdfinfo", str(path)],
                             capture_output=True, text=True).stdout
        found = re.search(r"Page size:\s+([\d.]+) x ([\d.]+) pts", out)
        if found:
            return float(found.group(1)) / 72.0, float(found.group(2)) / 72.0
    return None


def _runs(mask: np.ndarray):
    """Group consecutive True indices into (start, end) runs."""
    idx = np.where(mask)[0]
    if idx.size == 0:
        return []
    splits = np.where(np.diff(idx) > 1)[0]
    groups = np.split(idx, splits + 1)
    return [(int(g[0]), int(g[-1])) for g in groups]


def detect_rules(img: Image.Image, coverage: float = 0.55, tone: int = 244):
    """Find horizontal ruled lines and the vertical margin rule.

    A ruled line is a row where a large fraction of the pixels are darker
    than the page background. Rows are grouped into runs (a line is a few
    pixels thick) and each run contributes its centre.
    """
    arr = np.array(img)
    h, w = arr.shape[:2]
    luma = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    ink = luma < tone

    row_cov = ink.sum(axis=1) / w
    line_rows = row_cov > coverage
    centers = [(a + b) / 2.0 for a, b in _runs(line_rows)]

    spacing = None
    if len(centers) >= 3:
        diffs = np.diff(centers)
        # ignore stray pairs (page borders, headers) far from the typical gap
        med = float(np.median(diffs))
        keep = diffs[(diffs > med * 0.6) & (diffs < med * 1.4)]
        if keep.size:
            spacing = float(np.median(keep))

    col_cov = ink.sum(axis=0) / h
    margin_x = None
    col_runs = _runs(col_cov > coverage)
    if col_runs:
        # the margin rule is normally in the left third of the page
        left = [r for r in col_runs if (r[0] + r[1]) / 2 < w * 0.35]
        if left:
            a, b = max(left, key=lambda r: r[1])
            margin_x = (a + b) / 2.0

    return {
        "size_px": (w, h),
        "line_centers_px": centers,
        "line_spacing_px": spacing,
        "first_line_px": centers[0] if centers else None,
        "margin_x_px": margin_x,
        # page-relative fractions -- resolution independent
        "line_spacing_frac": (spacing / h) if spacing else None,
        "first_line_frac": (centers[0] / h) if centers else None,
        "margin_x_frac": (margin_x / w) if margin_x is not None else None,
        "line_count": len(centers),
    }


def describe(rules: dict) -> str:
    if not rules["line_spacing_px"]:
        return (f"No ruled lines detected ({rules['line_count']} candidate row(s)) -- "
                "falling back to the generated ruled paper.")
    w, h = rules["size_px"]
    margin = (f", margin rule at x={rules['margin_x_px']:.0f}px"
              if rules["margin_x_px"] is not None else ", no margin rule")
    return (f"Detected {rules['line_count']} ruled lines on a {w}x{h}px page: "
            f"spacing {rules['line_spacing_px']:.1f}px, "
            f"first line at y={rules['first_line_px']:.0f}px{margin}.")


if __name__ == "__main__":
    import sys
    img = load_page(Path(sys.argv[1]))
    r = detect_rules(img)
    print(describe(r))
