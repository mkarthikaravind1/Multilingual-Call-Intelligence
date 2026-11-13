"""Unicode script detection for native scripts.

Supported Indian scripts:
- Tamil (ta): U+0B80-U+0BFF
- Telugu (te): U+0C00-U+0C7F
- Kannada (kn): U+0C80-U+0CFF
- Malayalam (ml): U+0D00-U+0D7F
- Latin (en / romanized): U+0041-U+005A, U+0061-U+007A, plus common accented ranges
"""

from typing import Optional, Dict

UNICODE_RANGES = {
    "ta": (0x0B80, 0x0BFF),
    "te": (0x0C00, 0x0C7F),
    "kn": (0x0C80, 0x0CFF),
    "ml": (0x0D00, 0x0D7F),
}


def get_char_script(char: str) -> Optional[str]:
    """Return language code for native script character, 'latin' for Latin, or None."""
    cp = ord(char)
    for lang, (start, end) in UNICODE_RANGES.items():
        if start <= cp <= end:
            return lang
    if (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A):
        return "latin"
    return None


def count_script_chars(text: str) -> Dict[str, int]:
    """Count characters belonging to each script category in text."""
    counts: Dict[str, int] = {}
    for ch in text:
        script = get_char_script(ch)
        if script:
            counts[script] = counts.get(script, 0) + 1
    return counts

