"""langid: Standalone Language Detector for South Indian Service Calls.

Supports native scripts (Tamil, Telugu, Kannada, Malayalam, Latin) and
Romanised Indian languages (Tanglish, Tenglish, Kanglish, Manglish) with English.
"""

from langid.detector import identify

__all__ = ["identify"]
__version__ = "0.1.0"

