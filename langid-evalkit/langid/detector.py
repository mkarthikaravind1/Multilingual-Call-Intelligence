"""Language Detector for Native Scripts & Romanised Indian Languages.

Supported languages:
- ta: Tamil (native script + Romanised Tanglish)
- en: English
- te: Telugu (native script + Romanised Tenglish)
- kn: Kannada (native script + Romanised Kanglish)
- ml: Malayalam (native script + Romanised Manglish)

License: Apache-2.0
"""

import unicodedata
from typing import Dict, List, TypedDict

from langid.scripts import count_script_chars, get_char_script
from langid.romanized import classify_latin_token, tokenize_latin


class LanguageResult(TypedDict):
    language: str
    confidence: float


# Minimum confidence threshold to consider a language active in code-mixing
MIXED_THRESHOLD = 0.15


def identify(text: str) -> List[LanguageResult]:
    """Identify languages present in input text.

    Args:
        text: String input in native script, English, or Romanised Indian language.

    Returns:
        List of dicts {"language": code, "confidence": float}, sorted highest confidence first.
        Returns [] for empty, whitespace, digits-only, or unclear input.
    """
    if not text or not text.strip():
        return []

    # Normalize unicode to NFC
    normalized_text = unicodedata.normalize("NFC", text)

    # 1. Script character level counts
    script_counts = count_script_chars(normalized_text)
    total_script_chars = sum(script_counts.values())

    if total_script_chars == 0:
        return []

    # Language score accumulators
    lang_weights: Dict[str, float] = {"ta": 0.0, "en": 0.0, "te": 0.0, "kn": 0.0, "ml": 0.0}

    # Process native script characters
    native_script_total = 0
    for lang in ("ta", "te", "kn", "ml"):
        cnt = script_counts.get(lang, 0)
        if cnt > 0:
            lang_weights[lang] += cnt * 2.0  # Higher weight for distinctive native script
            native_script_total += cnt

    # Process Latin tokens (could be English or Romanised Indic)
    latin_chars = script_counts.get("latin", 0)
    if latin_chars > 0:
        latin_tokens = tokenize_latin(normalized_text)
        if latin_tokens:
            for tok in latin_tokens:
                pred_lang, weight = classify_latin_token(tok)
                lang_weights[pred_lang] += len(tok) * weight
        else:
            # Fallback if latin characters exist but no standard regex token
            lang_weights["en"] += latin_chars * 0.5

    # Filter out languages with 0 score
    active_scores = {lang: score for lang, score in lang_weights.items() if score > 0}
    if not active_scores:
        return []

    total_score = sum(active_scores.values())
    raw_results = [
        {"language": lang, "confidence": score / total_score}
        for lang, score in active_scores.items()
    ]

    # Sort descending by confidence
    raw_results.sort(key=lambda x: x["confidence"], reverse=True)

    # If top language dominates heavily (>= 85%), keep only top language
    if raw_results[0]["confidence"] >= 0.85:
        return [{"language": raw_results[0]["language"], "confidence": 1.0}]

    # Filter code-mixed results by threshold and renormalize
    filtered = [r for r in raw_results if r["confidence"] >= MIXED_THRESHOLD]
    if not filtered:
        filtered = [raw_results[0]]

    # Renormalize confidences of remaining languages so they sum to 1.0
    conf_sum = sum(r["confidence"] for r in filtered)
    results: List[LanguageResult] = [
        {
            "language": r["language"],
            "confidence": round(r["confidence"] / conf_sum, 2),
        }
        for r in filtered
    ]

    # Ensure exact sum of 1.0 when rounded if single item
    if len(results) == 1:
        results[0]["confidence"] = 1.0

    return results

