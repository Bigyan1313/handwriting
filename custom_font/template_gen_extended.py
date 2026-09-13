#!/usr/bin/env python3
"""Generate the two extra alphabet sets and second math set, with manifests."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from template_gen import build_manifest, build_html


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output-dir', type=Path, default=Path(__file__).parent / 'output')
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=['--no-sandbox'])
        except Exception:
            browser = p.chromium.launch(args=['--no-sandbox'], channel='chrome')
        for name, charset, label in [('set3', 'alphabet', 'Set 3 / Variant C'), ('set4', 'alphabet', 'Set 4 / Variant D'), ('math2', 'math', 'Math Set 2')]:
            manifest = build_manifest(charset, label)
            (args.output_dir / f'manifest_{name}.json').write_text(json.dumps(manifest, indent=2))
            page = browser.new_page()
            page.set_content(build_html(manifest))
            page.pdf(path=str(args.output_dir / f'template_{name}.pdf'), print_background=True, prefer_css_page_size=True)
            page.close()
            print(f'Generated template_{name}.pdf and manifest_{name}.json')
        browser.close()


if __name__ == '__main__':
    main()
