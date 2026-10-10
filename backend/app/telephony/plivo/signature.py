import base64
import hashlib
import hmac
from collections.abc import Mapping
from urllib.parse import parse_qs, urlsplit, urlunsplit

# Plivo V3 signature, for a POST webhook:
#   base64(HMAC-SHA256(key=auth_token, msg=signed_message(url, params, nonce)))
# as in Plivo's SDKs (plivo-python: plivo/utils/signature_v3.py). Unlike V2
# (url + nonce), the POST parameters are part of the signed message.
SIGNATURE_HEADER = "X-Plivo-Signature-V3"
NONCE_HEADER = "X-Plivo-Signature-V3-Nonce"


def signed_message(url: str, params: Mapping[str, str], nonce: str) -> str:
    """What Plivo signs: the URL (its query sorted), the POST parameters
    sorted by name and joined as name+value, then "." and the nonce."""
    parts = urlsplit(url)
    message = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    query = parse_qs(parts.query, keep_blank_values=True)
    query_string = "&".join(
        f"{name}={value}" for name in sorted(query) for value in sorted(query[name])
    )
    if query_string or params:
        message += "?" + query_string
    if query_string and params:
        message += "."
    message += "".join(f"{name}{params[name]}" for name in sorted(params))
    return f"{message}.{nonce}"


def compute_signature(
    auth_token: str, url: str, nonce: str, params: Mapping[str, str] | None = None
) -> str:
    digest = hmac.new(
        auth_token.encode("utf-8"),
        signed_message(url, params or {}, nonce).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def validate_signature(
    auth_token: str,
    headers: Mapping[str, str],
    url: str,
    params: Mapping[str, str] | None = None,
) -> bool:
    signature = headers.get(SIGNATURE_HEADER)
    nonce = headers.get(NONCE_HEADER)
    if not signature or not nonce:
        return False
    expected = compute_signature(auth_token, url, nonce, params)
    # The header can hold several signatures (the account's and a
    # subaccount's), separated by commas.
    return any(
        hmac.compare_digest(expected.encode("utf-8"), candidate.strip().encode("utf-8"))
        for candidate in signature.split(",")
    )
