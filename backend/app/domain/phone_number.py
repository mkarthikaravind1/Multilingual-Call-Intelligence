"""Caller phone numbers in one canonical form, so a number from the telephony
provider matches the same number stored in the CRM."""

import re

_MIN_DIGITS = 8
_MAX_DIGITS = 15  # E.164 upper bound
_NATIONAL_NUMBER_DIGITS = 10


def normalize_phone_number(raw: str | None, default_country_code: str = "") -> str | None:
    """Return the number as "+<digits>", or None if it is not a usable number.

    Separators and a leading "+" or "00" are ignored. A bare national number
    (10 digits, optionally with a trunk "0") gets default_country_code.
    Withheld or anonymous caller IDs, which carry no digits, give None.
    """
    if raw is None:
        return None

    text = raw.strip()
    digits = re.sub(r"\D", "", text)
    if text.startswith("00"):
        digits = digits[2:]
    elif not text.startswith("+"):
        if len(digits) == _NATIONAL_NUMBER_DIGITS + 1 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == _NATIONAL_NUMBER_DIGITS and default_country_code:
            digits = default_country_code.lstrip("+") + digits

    if not _MIN_DIGITS <= len(digits) <= _MAX_DIGITS:
        return None
    return f"+{digits}"
