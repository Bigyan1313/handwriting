"""The render spec: one document that fully describes an output.

Rendering is a pure function of a spec. That makes a render something you can
save, diff, hand to someone else, and re-run to the same bytes — rather than
something reconstructed from whichever command line you last typed.

    {
      "version": 1,
      "content": "notes.txt",
      "hand": "kalam",
      "paper": null,
      "font_size": 22,
      "line_height": 40,
      "seed": 1
    }

Only `content` is required; everything else falls back to a default, or to what
the chosen hand recommends for itself.
"""
import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

from handwriting import hands

SPEC_VERSION = 1
DEFAULT_FONT_SIZE = 22
DEFAULT_LINE_HEIGHT = 40
VARIANTS = 'ABCD'


@dataclass(frozen=True)
class RenderSpec:
    content: str                      # the text or LaTeX file to write out
    hand: str = 'kalam'               # a bundled font, or one of your own hands
    fonts: dict = None                # explicit variant paths, overriding `hand`
    paper: str = None                 # a ruled page to write onto; None generates one
    font_size: int = None             # None means the hand's own, or auto-sized to paper
    line_height: int = None
    seed: int = 1
    jitter: bool = True
    clean: bool = False               # input is already clean; skip paste repair
    hand_math: bool = False
    hand_delims: bool = True
    math_scale: float = 1.28
    bracket_stroke_scale: float = 1.0
    version: int = SPEC_VERSION

    def __post_init__(self):
        object.__setattr__(self, 'fonts', dict(self.fonts or {}))
        self.validate()

    def validate(self):
        if self.version != SPEC_VERSION:
            raise ValueError(f'unsupported spec version {self.version!r}; '
                             f'this build reads version {SPEC_VERSION}')
        if not self.content:
            raise ValueError('a spec needs `content`: the file to write out')
        for letter in self.fonts:
            if letter not in VARIANTS:
                raise ValueError(f'font variant {letter!r} is not one of {VARIANTS}')
        if self.fonts and 'A' not in self.fonts:
            raise ValueError('explicit fonts need at least variant A')
        if self.font_size is not None and self.font_size <= 0:
            raise ValueError('font_size must be positive')
        if self.line_height is not None and self.line_height <= 0:
            raise ValueError('line_height must be positive')
        if not 0 < self.bracket_stroke_scale < float('inf'):
            raise ValueError('bracket_stroke_scale must be finite and positive')
        if not 0 < self.math_scale < float('inf'):
            raise ValueError('math_scale must be finite and positive')

    # --- what the renderer actually needs ----------------------------------

    def resolved_hand(self):
        """The Hand this spec names, or None when it names a bundled font that
        is not installed as a hand."""
        return hands.find_hand(self.hand)

    def font_variants(self):
        """Variant letter to font path. Explicit `fonts` win; then the named
        hand's own files; a bundled font has none."""
        if self.fonts:
            return dict(self.fonts)
        hand = self.resolved_hand()
        return dict(hand.fonts) if hand and hand.fonts else {}

    def font_key(self):
        """Which bundled font to draw with, when there are no variant files."""
        return self.hand if self.hand in hands.FONTS else 'kalam'

    def metrics(self):
        """(font_size, line_height). A font_size of None means 'decide later' —
        either the plain default, or sized to the supplied paper's rules."""
        size, leading = self.font_size, self.line_height
        hand = self.resolved_hand()
        if hand is not None:
            if size is None:
                size = hand.font_size
            if leading is None:
                leading = hand.line_height
        return size, (leading if leading is not None else DEFAULT_LINE_HEIGHT)

    # --- persistence --------------------------------------------------------

    def to_dict(self):
        return asdict(self)

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2) + '\n'

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding='utf-8')
        return path

    def replace(self, **changes):
        """A copy with some fields changed — how a revision is applied."""
        return replace(self, **changes)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError('a spec must be a JSON object')
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f'unknown spec field(s): {", ".join(unknown)}')
        return cls(**data)

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8')))
