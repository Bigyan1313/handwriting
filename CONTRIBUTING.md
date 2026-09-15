# Contributing

Contributions are welcome: bug reports, documentation, handwriting improvements,
math layout fixes, accessibility improvements, and new features.

## Set up locally

Use Python 3.10 or newer. Fork the repository and clone your fork, then run:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

On Windows, activate with `.venv\Scripts\activate` instead.

## Make a change

1. Create a branch: `git switch -c describe-your-change`.
2. Make a focused change. For larger features, open an issue to discuss the design.
3. Run `python -m unittest discover -s tests -v`.
4. For rendering changes, run `python tests/browser_layout.py` and
   `python tests/browser_handwriting.py`, then render a sample:
   `python handwrite.py example_input.txt output/example.pdf`.
5. Open a pull request explaining the problem, resulting behavior, and checks run.
   Include a screenshot for visible changes, using sample text you can share.

`tests/browser_handwriting.py` uses your personal fonts when they are present
and otherwise builds a synthetic stand-in, so it runs on any checkout. Some
font-building checks still require personal glyph samples and skip without
them; explain any unavailable checks in your pull request.
Do not commit private documents, handwriting scans, generated PDFs, or credentials.

## Project structure

- `clean.py`: input cleanup, text/math parsing, and equation splitting.
- `handwrite.py`: fonts, HTML generation, and PDF rendering through Chromium.
- `layout.js`: measured page layout.
- `handwriting.js`: handwritten math and glyph selection.
- `delimiters.js`: handwritten stretchy brackets and their ink measurement.
- `random.js`: the shared seeded generator.
- `paper.py`: custom paper detection (PDF backgrounds also need Poppler).
- `hands.py`: which handwriting styles are available (no GUI dependencies).
- `custom_font/`: optional tools for building fonts from handwriting samples.
- `tests/`: parser, font, and browser checks.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit together,
the reasoning behind the main design decisions, and known limits.

## Bug reports

Include your operating system, Python version, command or UI steps, expected
result, actual result, and a small input that reproduces the issue. Remove
personal information first. For layout issues, attach `--analyze` output if possible.

By contributing, you agree to license your contributions under the project's MIT
license. Keep the existing notices for third-party assets.
