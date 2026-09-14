"""Which handwriting styles are available to render with.

A *hand* is either one of the bundled fonts in ``fonts/``, or a directory of
your own traced handwriting. Personal hands are looked for in, in order:

    $HANDWRITING_HANDS          an extra directory of hands, for testing or a
                                shared drive
    ~/.handwriting/hands/       where your own hands normally live
    custom_font/output/         the original single-hand location, still read

A hand directory holds up to four ``.ttf`` variants and an optional
``hand.json``::

    my-hand/
        hand.json     {"display": "My handwriting", "font_size": 30,
                       "line_height": 44}
        A.ttf B.ttf C.ttf D.ttf

Variants may be named ``A.ttf`` or ``<Anything>-A.ttf``; a single unsuffixed
font is taken as variant A. Everything here is deliberately free of GUI
dependencies, so the style logic stays importable on a headless machine.
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONTS = ('kalam', 'indieflower', 'patrickhand', 'caveat', 'reeniebeanie',
         'shadowsintolight', 'gochihand')
VARIANTS = 'ABCD'

USER_HANDS_DIR = Path.home() / '.handwriting' / 'hands'
# The original single-hand location, in a checkout. Absent from an installed
# copy, where your hands live under ~/.handwriting/hands instead.
LEGACY_FONT_DIR = HERE.parent / 'custom_font' / 'output'
PERSONAL_STYLE = 'My handwriting (Bigyan)'

# A hand built from handwriting usually has a smaller x-height than the stock
# fonts, so it needs a larger size to sit right on the same ruled lines.
DEFAULT_FONT_SIZE = 30
DEFAULT_LINE_HEIGHT = 44


@dataclass(frozen=True)
class Hand:
    """One selectable handwriting style.

    `options` is the command-line form, for the desktop app. `fonts` and the
    metrics are the same thing as data, for a render spec.
    """
    name: str          # stable identifier, e.g. 'kalam' or a directory name
    display: str       # what a person picks from a list
    options: tuple     # command-line options for handwrite.py
    fonts: dict = None # variant letter -> font path; empty for a bundled font
    font_size: int = None
    line_height: int = None

    @property
    def personal(self):
        return bool(self.fonts)

    def __post_init__(self):
        if self.fonts is None:
            object.__setattr__(self, 'fonts', {})


def _variant_paths(directory):
    """Map variant letter to font file, accepting 'A.ttf' and '<Name>-A.ttf'.

    A lone font with no variant suffix counts as A, so the original single-file
    layout keeps working.
    """
    found = {}
    for path in sorted(directory.glob('*.ttf')):
        stem = path.stem
        if len(stem) >= 2 and stem[-2] == '-' and stem[-1].upper() in VARIANTS:
            found.setdefault(stem[-1].upper(), path)
        elif len(stem) == 1 and stem.upper() in VARIANTS:
            found.setdefault(stem.upper(), path)
        else:
            found.setdefault('A', path)
    return found


def _read_metadata(directory):
    path = directory / 'hand.json'
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def hand_from_directory(directory):
    """Build a Hand from a directory, or None if it holds no usable font."""
    directory = Path(directory)
    variants = _variant_paths(directory)
    if 'A' not in variants:
        return None
    meta = _read_metadata(directory)
    legacy = directory.resolve() == LEGACY_FONT_DIR.resolve()
    default_display = PERSONAL_STYLE if legacy else directory.name
    font_size = int(meta.get('font_size', DEFAULT_FONT_SIZE))
    line_height = int(meta.get('line_height', DEFAULT_LINE_HEIGHT))
    options = ['--custom-font', str(variants['A']),
               '--font-size', str(font_size), '--line-height', str(line_height)]
    for letter in 'BCD':
        if letter in variants:
            options.extend([f'--custom-font-{letter.lower()}', str(variants[letter])])
    return Hand(name=directory.name,
                display=str(meta.get('display', default_display)),
                options=tuple(options),
                fonts={letter: str(path) for letter, path in sorted(variants.items())},
                font_size=font_size, line_height=line_height)


def hand_directories():
    """Every directory that might hold a personal hand, in preference order."""
    directories = []
    roots = []
    extra = os.environ.get('HANDWRITING_HANDS')
    if extra:
        roots.append(Path(extra))
    roots.append(USER_HANDS_DIR)
    for root in roots:
        if root.is_dir():
            directories.extend(sorted(p for p in root.iterdir() if p.is_dir()))
    if LEGACY_FONT_DIR.is_dir():
        directories.append(LEGACY_FONT_DIR)
    return directories


def personal_hands():
    """Your own hands, nearest search root first."""
    found, seen = [], set()
    for directory in hand_directories():
        hand = hand_from_directory(directory)
        if hand and hand.display not in seen:
            seen.add(hand.display)
            found.append(hand)
    return found


def stock_hands():
    """The handwriting fonts bundled in fonts/."""
    return [Hand(name=name, display=name, options=('--font', name)) for name in FONTS]


def available_hands():
    """Personal hands first, so one is picked by default when you have one."""
    return personal_hands() + stock_hands()


def find_hand(key):
    """Look a hand up by display name or identifier. None if there is no match."""
    for hand in available_hands():
        if key in (hand.display, hand.name):
            return hand
    return None


# --- compatibility with the original two-function interface -----------------

def available_styles():
    return tuple(hand.display for hand in available_hands())


def personal_font_options(directory=None):
    """Options for the hand in ``directory`` (the legacy location by default)."""
    directory = Path(directory) if directory is not None else LEGACY_FONT_DIR
    hand = hand_from_directory(directory)
    if hand is None:
        raise FileNotFoundError(
            f'No handwriting font found in {directory}. Add a font named A.ttf '
            '(or BigyanHand-A.ttf) there and restart the app.')
    return list(hand.options)
