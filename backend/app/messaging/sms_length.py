"""How many SMS parts a text takes.

A text in the GSM 7-bit alphabet holds 160 characters, or 153 per part once
it is split. Anything else (Tamil, Hindi, emoji, curly quotes...) is sent as
UCS-2: 70 characters, or 67 per part.
"""

import math

_GSM_BASIC = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
# These take two characters each.
_GSM_EXTENDED = frozenset("^{}\\[~]|€\f")


def sms_parts(text: str) -> int:
    if all(char in _GSM_BASIC or char in _GSM_EXTENDED for char in text):
        length = sum(2 if char in _GSM_EXTENDED else 1 for char in text)
        single, per_part = 160, 153
    else:
        length = len(text.encode("utf-16-be")) // 2
        single, per_part = 70, 67
    if length <= single:
        return 1
    return math.ceil(length / per_part)
