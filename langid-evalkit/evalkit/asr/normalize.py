"""ASR Transcript Normalization.

Indian script and multilingual text normalization rules:
1. Unicode NFC Normalization: Converts decomposed combining characters into canonical composed forms.
2. Zero-Width Character Removal: Strips ZWJ (U+200D), ZWNJ (U+200C), and BOM (U+FEFF), which
   vary across keyboards/ASR models but do not change speech semantics.
3. Punctuation Removal: Strips ASCII punctuation and Unicode symbols/dandas (U+0964, U+0965).
4. Case Folding: Lowercases Latin characters.
5. Whitespace Collapse: Strips extra whitespace, replacing consecutive tabs/newlines/spaces with a single space.
"""

import re
import unicodedata

# Unicode dandas, quotes, dashes, and standard punctuation
PUNCT_PATTERN = re.compile(r"[\.,;:!\?\"'’‘“”`~@#\$%\^&\*\(\)\-_\+=\[\]\{\}\|\\/<>\u0964\u0965\u2014\u2013\u2026]")
ZERO_WIDTH_PATTERN = re.compile(r"[\u200B-\u200D\uFEFF]")
MULTI_SPACE_PATTERN = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normalize transcript text for consistent WER / CER calculation.

    Args:
        text: Raw transcript or reference string.

    Returns:
        Canonical normalized string.
    """
    if not text:
        return ""

    # 1. NFC normalization
    text = unicodedata.normalize("NFC", text)

    # 2. Strip zero-width characters
    text = ZERO_WIDTH_PATTERN.sub("", text)

    # 3. Lowercase (affects Latin scripts)
    text = text.lower()

    # 4. Remove punctuation
    text = PUNCT_PATTERN.sub(" ", text)

    # 5. Collapse whitespace
    text = MULTI_SPACE_PATTERN.sub(" ", text).strip()

    return text

