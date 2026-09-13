"""Shared character sets + naming for the custom-handwriting-font pipeline."""

LOWERCASE = list("abcdefghijklmnopqrstuvwxyz")
UPPERCASE = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
DIGITS = list("0123456789")
# Append additions so previously completed sheet coordinates remain valid.
PUNCT = list(".,;:!?'\"()-+=/#")

ALPHABET_PAGES = [
    ("lowercase", "Lowercase letters", LOWERCASE),
    ("uppercase", "Uppercase letters", UPPERCASE),
    ("digits_punct", "Digits & punctuation", DIGITS + PUNCT),
]

# Math symbols, as (character, human-readable name). The name is printed in
# the corner of the box so it's obvious what to write.
DELIMS_OPS = [
    ("[", "left bracket"), ("]", "right bracket"),
    ("{", "left brace"), ("}", "right brace"),
    ("|", "vertical bar"), ("−", "minus (math)"),
    ("×", "times"), ("÷", "divide"),
    ("±", "plus-minus"), ("∓", "minus-plus"),
    ("·", "dot product"), ("≠", "not equal"),
    ("≈", "approx"), ("≡", "equivalent"),
    ("<", "less than"), (">", "greater than"),
    ("≤", "less or equal"), ("≥", "greater or equal"),
    ("∝", "proportional"), ("≅", "congruent"),
    ("∴", "therefore"), ("…", "ellipsis"),
]

GREEK = [
    ("α", "alpha"), ("β", "beta"), ("γ", "gamma"), ("δ", "delta"),
    ("ε", "epsilon"), ("θ", "theta"), ("λ", "lambda"), ("μ", "mu"),
    ("π", "pi"), ("ρ", "rho"), ("σ", "sigma"), ("τ", "tau"),
    ("φ", "phi"), ("ω", "omega"),
    ("Γ", "cap gamma"), ("Δ", "cap delta"), ("Θ", "cap theta"),
    ("Λ", "cap lambda"), ("Π", "cap pi"), ("Σ", "cap sigma"),
    ("Φ", "cap phi"), ("Ω", "cap omega"),
]

SYMBOLS = [
    ("√", "square root"), ("∑", "sum"), ("∏", "product"), ("∫", "integral"),
    ("∞", "infinity"), ("∈", "element of"), ("∉", "not element of"),
    ("⊂", "subset"), ("⊆", "subset or equal"), ("∪", "union"),
    ("∩", "intersection"), ("∀", "for all"), ("∃", "there exists"),
    ("∅", "empty set"), ("→", "right arrow"), ("←", "left arrow"),
    ("↔", "both arrow"), ("⇒", "implies"), ("⇔", "iff"),
    ("∂", "partial"), ("∇", "nabla"), ("⊥", "perpendicular"),
    ("∥", "parallel"), ("∠", "angle"), ("°", "degree"), ("′", "prime"),
]

MATH_PAGES = [
    ("delims_ops", "Brackets & operators", DELIMS_OPS),
    ("greek", "Greek letters", GREEK),
    ("symbols", "Math symbols", SYMBOLS),
]

ALL_CHARS = LOWERCASE + UPPERCASE + DIGITS + PUNCT
ALL_MATH = [c for _, _, page in MATH_PAGES for c, _ in page]


def safe_name(ch: str) -> str:
    """Filesystem-safe, unambiguous name for a character."""
    return f"u{ord(ch):04X}"


def pages_for(set_name: str):
    """Return [(page_key, page_title, [(char, label_note), ...]), ...]."""
    if set_name == "math":
        return MATH_PAGES
    return [(k, t, [(c, "") for c in chars]) for k, t, chars in ALPHABET_PAGES]
