from app.core.constants import SUPPORTED_LANGUAGES

ENGLISH = "en"

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
}

# Unicode block of each Indian language's own script.
_SCRIPT_RANGES: dict[str, tuple[int, int]] = {
    "ta": (0x0B80, 0x0BFF),
    "te": (0x0C00, 0x0C7F),
    "kn": (0x0C80, 0x0CFF),
    "ml": (0x0D00, 0x0D7F),
}

INDIC_LANGUAGES: tuple[str, ...] = tuple(
    language for language in SUPPORTED_LANGUAGES if language in _SCRIPT_RANGES
)


def language_name(language: str) -> str:
    return LANGUAGE_NAMES.get(language, language)


def is_written_in_script(text: str, language: str) -> bool:
    """Whether text is written mainly in the language's own script (English
    words in Latin script may be mixed in). Always True for English."""
    script = _SCRIPT_RANGES.get(language)
    if script is None:
        return True
    low, high = script
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    native = sum(1 for char in letters if low <= ord(char) <= high)
    return native / len(letters) >= 0.5
