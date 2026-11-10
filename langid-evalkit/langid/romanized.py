"""Romanised South Indian Language Detector.

Detects whether Latin-script tokens / phrases represent English (en),
Romanised Tamil (ta), Romanised Telugu (te), Romanised Kannada (kn),
or Romanised Malayalam (ml).

License: Apache-2.0
Execution time: < 0.2 ms on standard CPU. Zero heavy dependencies.
"""

import re
from typing import Dict, List, Optional, Tuple

# High-frequency Romanised lexicons for automotive customer service calls
ROMANIZED_LEXICONS = {
    "ta": {
        # Greetings & conversational
        "vanakkam", "solunga", "sollunga", "sir", "madam", "aama", "aamam", "illai", "illa",
        "seri", "sari", "romba", "nalla", "enna", "edhu", "epdi", "eppo", "enga", "yaar",
        "ethuku", "edhukku", "ippo", "appo", "aprom", "adhu", "idhu", "oru", "dhaan", "thaan",
        # Automotive & service verbs/nouns in Tanglish
        "sariya", "aagala", "aagiduchu", "aachu", "irukku", "irukkum", "illama", "theriyala",
        "purila", "pannunga", "pannanum", "kudunga", "kuduthom", "vandhu", "vandha", "vandi",
        "paathen", "paatha", "paathu", "kekkudhu", "kekkala", "kaasu", "panam", "selavu",
        "kooda", "mattum", "mudiyum", "mudiyathu", "mudiyala", "kelvi", "solli", "kettan",
        "kettanga", "potrukanga", "maathunga", "maathanum", "maathi", "anupunga", "pesaren",
        "pesuringa", "ungaluku", "ungaloda", "engaluku", "enakku", "namma", "kitta",
    },
    "te": {
        # Greetings & conversational
        "namaskaram", "cheppandi", "enti", "ela", "eppudu", "ekkada", "enduku", "avunu", "kadu",
        "ledu", "undhi", "undi", "unnara", "chala", "babu", "gari", "andi", "adi", "idi",
        # Automotive & service in Tenglish
        "avvaledu", "ayipoyindi", "chesaru", "chestharu", "cheyandi", "ivvandi", "ippudu",
        "choosi", "pettandi", "vastundi", "raaledu", "baga", "bagundi", "kavala", "kavali",
        "thondaraga", "dabbu", "billu", "kottandi", "marchandi", "sahayam", "matladuthunnanu",
        "meeru", "naaku", "maaku", "manaki", "garu", "vachindi", "pani", "cheyatam",
    },
    "kn": {
        # Greetings & conversational
        "namaskara", "helidhe", "heli", "enu", "hege", "yaavaga", "elli", "yaake", "houdu",
        "alla", "illa", "ide", "agide", "aythu", "aayithu", "thumba", "tumba", "swalpa",
        # Automotive & service in Kanglish
        "agilla", "beku", "beda", "madilla", "madabeku", "madidhe", "nodona", "kodi",
        "thondre", "nimma", "namma", "illi", "baralla", "bandide", "banni", "kelasa",
        "koduva", "kottidhe", "maduthidhe", "matanaduthiddini", "gottilla", "bekagide",
    },
    "ml": {
        # Greetings & conversational
        "namaskaram", "parayu", "entha", "engane", "eppol", "evide", "enthukondu", "athe",
        "alla", "illa", "undu", "aanu", "valare", "kurachu", "pinne", "athaanu", "ithaanu",
        # Automotive & service in Manglish
        "cheyyanam", "cheythu", "cheyyilla", "kazhinju", "vannu", "varilla", "patti",
        "ariyo", "nokkam", "sahayikkamo", "tharam", "tharilla", "poyi", "kittilla", "kittumo",
        "pani", "nannayi", "ingane", "enikku", "njangalkku", "ningalude", "samsarikkunnu",
    },
}

# Common English words strongly indicating English context
ENGLISH_VOCAB = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it", "for", "not", "on",
    "with", "he", "as", "you", "do", "at", "this", "but", "his", "by", "from", "they", "we",
    "say", "her", "she", "or", "an", "will", "my", "one", "all", "would", "there", "their",
    "what", "so", "up", "out", "if", "about", "who", "get", "which", "go", "me", "when", "make",
    "can", "like", "time", "no", "just", "him", "know", "take", "people", "into", "year", "your",
    "good", "some", "could", "them", "see", "other", "than", "then", "now", "look", "only", "come",
    "its", "over", "think", "also", "back", "after", "use", "two", "how", "our", "work", "first",
    "well", "way", "even", "new", "want", "because", "any", "these", "give", "day", "most", "us",
    # Automotive service specific English
    "car", "vehicle", "brake", "brakes", "engine", "oil", "service", "problem", "issue", "bill",
    "charge", "charges", "cost", "customer", "executive", "battery", "clutch", "gear", "filter",
    "noise", "sound", "light", "indicator", "bumper", "door", "wheel", "alignment", "ac",
    "cooling", "air", "conditioning", "mechanic", "advisor", "manager", "turnaround", "time",
    "delivery", "delay", "hygiene", "wash", "cleaning", "hospitality", "behaviour", "staff",
    "documentation", "estimate", "quotation", "warranty", "insurance", "claim", "appointment",
    "morning", "evening", "today", "tomorrow", "check", "checked", "replace", "replaced", "fixed",
    "hello", "hi", "sir", "madam", "please", "thanks", "thank", "okay", "ok", "yes", "sure",
}

# Characteristic n-grams for Romanised Indic languages vs English
INDIC_CHAR_NGRAMS = {
    "ta": ["aag", "gala", "achu", "rkku", "llai", "padi", "enga", "unga", "dhan", "than", "athu", "ithu", "kku", "nnu", "ttu"],
    "te": ["andi", "ppan", "valo", "endu", "ledh", "ledu", "undh", "undi", "adam", "tund", "thun"],
    "kn": ["gide", "agil", "beku", "didd", "dhe", "ndid", "tumb", "ttid"],
    "ml": ["yyan", "nnam", "zhin", "aanu", "kkam", "yumo", "kkun"],
}


def tokenize_latin(text: str) -> List[str]:
    """Extract lowercased Latin alphabetic tokens."""
    return [w.lower() for w in re.findall(r"[A-Za-z]+", text)]


def classify_latin_token(token: str) -> Tuple[str, float]:
    """Classify a single Latin word into ta, te, kn, ml, or en.

    Returns (language_code, confidence_weight).
    """
    token_lower = token.lower()

    # Exact vocabulary match
    for lang, vocab in ROMANIZED_LEXICONS.items():
        if token_lower in vocab:
            return lang, 1.0

    if token_lower in ENGLISH_VOCAB:
        return "en", 1.0

    # N-gram matching
    ngram_scores: Dict[str, int] = {lang: 0 for lang in INDIC_CHAR_NGRAMS}
    for lang, ngrams in INDIC_CHAR_NGRAMS.items():
        for ng in ngrams:
            if ng in token_lower:
                ngram_scores[lang] += 1

    best_indic_lang = max(ngram_scores, key=ngram_scores.get)
    best_score = ngram_scores[best_indic_lang]

    if best_score >= 1:
        return best_indic_lang, 0.7

    # Suffix heuristics for South Indian languages:
    # Tamil verbal/case suffixes: -aagala, -udhu, -anga, -unga, -aachu, -kitta
    if any(token_lower.endswith(sfx) for sfx in ("aagala", "udhu", "anga", "unga", "aachu", "kitta", "romba")):
        return "ta", 0.8
    # Telugu verbal suffixes: -thundi, -aledu, -gari, -andi
    if any(token_lower.endswith(sfx) for sfx in ("thundi", "tundi", "aledu", "avvaledu", "andi", "gari")):
        return "te", 0.8
    # Kannada: -beku, -agilla, -agide
    if any(token_lower.endswith(sfx) for sfx in ("beku", "agilla", "agide", "iddini")):
        return "kn", 0.8
    # Malayalam: -anam, -unnu, -illa, -undu
    if any(token_lower.endswith(sfx) for sfx in ("anam", "unnu", "ichu", "undu")):
        return "ml", 0.8

    # Default fallback for unrecognised Latin word
    return "en", 0.5

