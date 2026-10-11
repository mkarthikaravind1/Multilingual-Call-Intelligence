"""Text in a PDF export, in Latin script or in Tamil, Telugu, Kannada or
Malayalam.

The PDF library's built-in fonts print Latin script only. For the four
Indian scripts the Noto Sans fonts are bundled (app/assets/fonts, from
Google Fonts under the SIL Open Font License) and the text is shaped with
HarfBuzz, which puts vowel signs and joined letters where they belong;
without shaping the letters come out one by one, in the wrong order.

A paragraph is set in the font of the script it mostly holds. Those fonts
carry Latin letters, digits and the rupee sign too, so mixed text such as
"Estimate-ல ₹4000" prints whole. What no available font can print (another
script in the same paragraph, an emoji) is left out as "[...]", and
`left_out` says so for the export to mention.
"""

import logging
import re
from pathlib import Path
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)

FONT_DIRECTORY = Path(__file__).resolve().parent.parent / "assets" / "fonts"
# Script -> its Unicode block.
SCRIPTS = {
    "Tamil": (0x0B80, 0x0BFF),
    "Telugu": (0x0C00, 0x0C7F),
    "Kannada": (0x0C80, 0x0CFF),
    "Malayalam": (0x0D00, 0x0D7F),
}
LEFT_OUT = "[...]"
LEFT_OUT_NOTE = (
    "Some text could not be printed in this PDF and is shown as [...]. The Excel and "
    "CSV exports carry it in full."
)
# What the built-in fonts print: Latin-1 and the punctuation people type.
_LATIN = re.compile("[^\\x00-\\xff\\u2010-\\u2027\\u2030-\\u205e]+")
# Joiners shape the letters around them and print nothing themselves.
_JOINERS = frozenset({0x200C, 0x200D})
_RUPEE = "₹"


def _script_of(character: str) -> str | None:
    code = ord(character)
    for script, (first, last) in SCRIPTS.items():
        if first <= code <= last:
            return script
    return None


def font_name(script: str) -> str:
    return f"NotoSans{script}"


class PdfText:
    """Makes the paragraphs of one PDF. left_out: whether anything had to
    be left out of any of them."""

    def __init__(self) -> None:
        self.left_out = False
        self._styles: dict[tuple[str, str], object] = {}

    def paragraph(self, value, style):
        """A paragraph of the text in `style`, or in the font of its script."""
        from reportlab.platypus import Paragraph

        text = str(value)
        script = self._main_script(text)
        font = self._font(script) if script is not None else None
        if font is None:
            # No rupee sign in the built-in fonts.
            printable = _LATIN.sub(LEFT_OUT, text.replace(_RUPEE, "Rs "))
            self.left_out = self.left_out or LEFT_OUT in printable and LEFT_OUT not in text
            return Paragraph(escape(printable), style)
        printable = self._printable_in(font, text)
        return Paragraph(escape(printable), self._style_for(style, font))

    @staticmethod
    def _main_script(text: str) -> str | None:
        counts: dict[str, int] = {}
        for character in text:
            script = _script_of(character)
            if script is not None:
                counts[script] = counts.get(script, 0) + 1
        return max(counts, key=counts.get) if counts else None

    @staticmethod
    def _font(script: str):
        """The script's registered font; None when it cannot be loaded
        (the text is then left out, as before the fonts were bundled)."""
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        name = font_name(script)
        try:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(FONT_DIRECTORY / f"{name}.ttf")))
            font = pdfmetrics.getFont(name)
        except Exception:
            logger.exception("The %s font for PDF exports could not be loaded", script)
            return None
        # Without shaping the letters would print in the wrong order.
        return font if getattr(font, "shapable", False) else None

    def _printable_in(self, font, text: str) -> str:
        known = font.face.charToGlyph
        parts: list[str] = []
        missing = False
        for character in text:
            code = ord(character)
            if code in known or code in _JOINERS or character in "\n\t":
                parts.append(character)
                missing = False
            elif not missing:
                parts.append(LEFT_OUT)
                missing = True
                self.left_out = True
        return "".join(parts)

    def _style_for(self, style, font):
        key = (style.name, font.fontName)
        if key not in self._styles:
            self._styles[key] = style.clone(
                f"{style.name}-{font.fontName}",
                fontName=font.fontName,
                shaping=1,
                # These scripts stand taller than Latin at the same size.
                leading=max(style.leading, style.fontSize * 1.6),
            )
        return self._styles[key]
