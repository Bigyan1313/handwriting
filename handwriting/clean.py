"""
Cleanup + parsing for messy copy-pasted math solutions.

Turns raw pasted text (which may contain duplicated "flattened" renderer
artifacts like `Axsvg`, `x1svg851svg...`) into a clean list of blocks:

    ("heading", text)
    ("para", [ ("text", str) | ("math", latex, inline_bool), ... ])
    ("display_math", latex)

Two things make the messy paste hard:
  1. Every backtick-quoted math span `LaTeX` is immediately followed
     (no space) by a garbage duplicate: the same expression with LaTeX
     commands stripped down to bare letters/digits, plus a trailing
     "svg" marker (e.g. `A\\vec x` -> Axsvg). We drop that duplicate.
  2. Every ```math fenced block is followed by a similar flattened
     duplicate line, which we drop (the fenced block itself is clean,
     real LaTeX, so we keep that).
  3. Occasionally a line's own opening words repeat themselves (a
     truncated copy immediately followed by the full copy) -- we
     collapse that too.
"""
import re

SVG_TAIL_RE = re.compile(r'^[A-Za-z0-9+\-=,.\\]*svg$')


def dedup_prefix_glitch(line: str, min_match: int = 10, max_search: int = 200) -> str:
    """Collapse 'truncated-copy immediately followed by full copy' glitches,
    e.g. 'The matrix is 3x2 (2The matrix is 3x2 (2 columns)...' ->
    'The matrix is 3x2 (2 columns)...'
    """
    n = len(line)
    upper = min(max_search, n // 2 if n // 2 > 0 else n)
    for L in range(upper, min_match - 1, -1):
        prefix = line[:L]
        idx = line.find(prefix, 1)
        if idx != -1 and idx <= max_search:
            return line[idx:]
    return line


DEBRIS_LEAD_RE = re.compile(r'^[A-Za-z0-9+\-=−]+')


def reconstruct_backtick_pairs(line: str) -> str:
    """The messy source never actually *closes* a backtick math span --
    each math mention is written as two bare, unclosed backticks in a row:
    one opening the real LaTeX, one opening a flattened duplicate of it,
    e.g.:
        `A\\vec x `Axsvg, the rest of the sentence
    Splitting on backtick gives: [prose, REAL, DEBRIS+prose, REAL, ...]
    (real math at odd positions, debris-then-real-prose at even positions).
    This turns that into proper `` `REAL` `` spans followed by the real
    trailing prose, with the leading debris token stripped off.
    """
    if line.count('`') < 2:
        return line
    parts = line.split('`')
    out = [parts[0]]
    i = 1
    while i < len(parts):
        real = parts[i].strip()
        out.append(f'`{real}`')
        if i + 1 < len(parts):
            rest = parts[i + 1]
            rest = DEBRIS_LEAD_RE.sub('', rest, count=1)
            out.append(rest)
        i += 2
    return ''.join(out)


def strip_svg_junk_lines(text: str) -> str:
    """Drop whole lines that are pure flattened-math debris: they contain
    'svg' and are otherwise just digits/letters/operators/brackets with no
    real prose words (no run of 4+ alphabetic letters that isn't 'svg').
    """
    out_lines = []
    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped:
            out_lines.append(line)
            continue
        if 'svg' in stripped.lower():
            # does this line contain any "real" word (alphabetic run of
            # length >= 4, once every 'svg' marker inside it is removed)?
            words = re.findall(r'[A-Za-z]{4,}', stripped)
            real_words = [
                w for w in words
                if len(re.sub('svg', '', w, flags=re.IGNORECASE)) >= 3
            ]
            # if there are no real words at all, it's flattened-math junk
            if not real_words:
                continue  # drop this line entirely
        out_lines.append(line)
    return '\n'.join(out_lines)


FENCE_PROTECT_RE = re.compile(r'```math\s*\n.*?```', re.DOTALL)


def clean_messy_text(raw: str):
    """Run the full messy-paste cleanup pipeline. Returns (cleaned_text, notes).

    Fenced ```math blocks are real, trusted LaTeX -- they're protected
    behind placeholders for the whole pipeline so no heuristic can mangle
    the math itself, then restored verbatim at the end.
    """
    notes = []

    protected = {}

    def _protect(m):
        key = f"\x00MATHBLOCK{len(protected)}\x00"
        protected[key] = m.group(0)
        return key

    text = FENCE_PROTECT_RE.sub(_protect, raw)

    lines = text.split('\n')
    fixed_lines = []
    for line in lines:
        new_line = reconstruct_backtick_pairs(line)
        if new_line != line:
            notes.append("reconstructed backtick math span(s), dropped glued debris")
        newer = dedup_prefix_glitch(new_line)
        if newer != new_line:
            notes.append(f"collapsed repeated-prefix glitch: {new_line[:50]!r}...")
        fixed_lines.append(newer)
    text = '\n'.join(fixed_lines)

    before = text
    text = strip_svg_junk_lines(text)
    if text != before:
        notes.append("dropped standalone flattened-math debris lines")

    for key, original in protected.items():
        text = text.replace(key, original)

    # Warn about anything that still looks like leftover debris so the user
    # can double check that specific spot before printing/submitting.
    for i, line in enumerate(text.split('\n')):
        if re.search(r'\b[a-z]*svg\b', line, re.IGNORECASE) and '```' not in line:
            notes.append(f"WARNING: possible leftover artifact, please check line: {line!r}")

    return text, notes


# ---------------------------------------------------------------------------
# Block parsing (works on already-cleaned text)
# ---------------------------------------------------------------------------

FENCE_RE = re.compile(r'```math\s*\n(.*?)```', re.DOTALL)
INLINE_BACKTICK_RE = re.compile(r'`([^`\n]+?)`')
DOLLAR_DISPLAY_RE = re.compile(r'\$\$(.+?)\$\$', re.DOTALL)
DOLLAR_INLINE_RE = re.compile(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)')
HEADING_RE = re.compile(r'^\s*(?:#{1,6}\s+.*|\d+(?:\.\d+)*\s*#\d+|(?:Problem|Question)\s+\d+|\d+[.)](?=\s))\s*(?:—|-|:)?\s*', re.I)


def equation_parts(latex: str):
    """Safe continuation points outside braces, environments and left/right pairs.

    Keep the operator (and its complete annotation) on the continuation line.
    Never split matrix rows, nested arrow labels, products, or aligned groups.
    """
    token = re.compile(r'\\(?:begin|end)\{[^}]+\}|\\(?:left|right)(?![A-Za-z])|\\[A-Za-z]+|\\.|[{}=]')
    depth = env = delimiters = 0
    cuts = []
    operators = {r'\xrightarrow', r'\xleftarrow', r'\rightarrow', r'\Rightarrow', r'\to', '='}
    for m in token.finditer(latex):
        t = m.group()
        if t in operators and depth == env == delimiters == 0 and latex[:m.start()].strip():
            cuts.append(m.start())
        if t.startswith(r'\begin{'): env += 1
        elif t.startswith(r'\end{'): env -= 1
        elif t == r'\left': delimiters += 1
        elif t == r'\right': delimiters -= 1
        elif t == '{': depth += 1
        elif t == '}': depth -= 1
    if depth or env or delimiters:
        return [latex]
    offsets = [0] + cuts + [len(latex)]
    return [latex[a:b] for a, b in zip(offsets, offsets[1:])]


def split_long_display_math(latex: str, max_per_line: int = 2):
    if max_per_line < 1:
        raise ValueError('max_per_line must be positive')
    parts = equation_parts(latex)
    result, current, count = [], '', 0
    for part in parts:
        n = len(re.findall(r'\\begin\{(?:[bpBvV]?matrix|array)\}', part))
        if current and count + n > max_per_line:
            result.append(current.strip())
            current, count = '', 0
        current += part
        count += n
    if current:
        result.append(current.strip())
    return result or [latex]


def group_problems(blocks):
    groups, current = [], []
    for block in blocks:
        starts = block[0] == 'para' and any(seg[0] == 'label' for seg in block[1])
        if starts and current:
            groups.append(('problem_group', current))
            current = []
        current.append(block)
    if current:
        groups.append(('problem_group', current))
    return groups


def parse_blocks(text: str, grouped: bool = False):
    """Split cleaned text into a list of blocks: display math, headings,
    and paragraphs (paragraphs are lists of ('text', s) / ('math', s, True)
    segments).
    """
    blocks = []

    # First pull out ```math fenced blocks and $$...$$ blocks (both can span
    # multiple lines) as standalone display-math blocks, splitting the
    # surrounding text around them.
    DISPLAY_BLOCK_RE = re.compile(
        r'```math\s*\n(.*?)```' r'|' r'\$\$(.+?)\$\$',
        re.DOTALL,
    )
    pos = 0
    parts = []  # list of ('raw', text) / ('display', latex)
    for m in DISPLAY_BLOCK_RE.finditer(text):
        if m.start() > pos:
            parts.append(('raw', text[pos:m.start()]))
        latex = m.group(1) if m.group(1) is not None else m.group(2)
        parts.append(('display', latex.strip()))
        pos = m.end()
    if pos < len(text):
        parts.append(('raw', text[pos:]))

    for kind, content in parts:
        if kind == 'display':
            blocks.append(('display_math', content))
            continue
        # split raw text into lines/paragraphs
        for raw_line in content.split('\n'):
            line = raw_line.strip()
            if not line:
                continue
            m = HEADING_RE.match(line)
            if m:
                label = m.group(0).rstrip()
                rest = line[m.end():]
                segs = [('label', label)]
                if rest.strip():
                    segs.append(('text', ' '))
                    segs.extend(parse_inline(rest))
                blocks.append(('para', segs))
                continue
            blocks.append(('para', parse_inline(line)))

    return group_problems(blocks) if grouped else blocks


def parse_inline(line: str):
    """Parse a single line of prose into text/math segments, recognizing
    $$...$$, $...$, and backtick-quoted math spans.
    """
    # Normalize: treat $$...$$ as display-ish but keep inline here (rare
    # mid-sentence); handle $...$ and backticks uniformly via one pass.
    token_re = re.compile(r'\$\$(.+?)\$\$|\$(.+?)\$|`([^`\n]+?)`')
    segments = []
    pos = 0
    for m in token_re.finditer(line):
        if m.start() > pos:
            segments.append(('text', line[pos:m.start()]))
        latex = next(g for g in m.groups() if g is not None)
        segments.append(('math', latex.strip(), True))
        pos = m.end()
    if pos < len(line):
        segments.append(('text', line[pos:]))
    return segments


if __name__ == '__main__':
    with open('example_input.txt') as f:
        raw = f.read()
    cleaned, notes = clean_messy_text(raw)
    print("=== NOTES ===")
    for n in notes:
        print(" -", n)
    print("\n=== CLEANED TEXT ===")
    print(cleaned)
    print("\n=== BLOCKS ===")
    for b in parse_blocks(cleaned):
        print(b)
