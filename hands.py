"""Which handwriting styles are available to render with.

Imported by the desktop app, but deliberately free of GUI dependencies so the
style logic stays importable (and testable) on a machine without Tk.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONTS = ('kalam', 'indieflower', 'patrickhand', 'caveat', 'reeniebeanie',
         'shadowsintolight', 'gochihand')
PERSONAL_STYLE = 'My handwriting (Bigyan)'
PERSONAL_FONT_DIR = HERE / 'custom_font' / 'output'


def personal_font_options(directory=None):
    """Use the supplied personal font and any available alternate letter samples."""
    directory = Path(directory) if directory is not None else PERSONAL_FONT_DIR
    primary = directory / 'BigyanHand-A.ttf'
    if not primary.is_file():
        primary = directory / 'BigyanHand.ttf'
    if not primary.is_file():
        raise FileNotFoundError('Your handwriting font is missing. Restore '
                                'BigyanHand-A.ttf in custom_font/output and restart the app.')
    options = ['--custom-font', str(primary), '--font-size', '30', '--line-height', '44']
    for variant in 'BCD':
        path = directory / f'BigyanHand-{variant}.ttf'
        if path.is_file():
            options.extend([f'--custom-font-{variant.lower()}', str(path)])
    return options


def available_styles():
    try:
        personal_font_options()
    except FileNotFoundError:
        return FONTS
    return (PERSONAL_STYLE, *FONTS)
