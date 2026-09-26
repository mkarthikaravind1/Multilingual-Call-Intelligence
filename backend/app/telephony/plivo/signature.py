import base64
import hashlib
import hmac
from collections.abc import Mapping

# Plivo V3 signature: base64(HMAC-SHA256(key=auth_token, msg=url + nonce)).
# Unlike V2, the request body/params are not part of the signed message.
SIGNATURE_HEADER = "X-Plivo-Signature-V3"
NONCE_HEADER = "X-Plivo-Signature-V3-Nonce"


def compute_signature(auth_token: str, url: str, nonce: str) -> str:
    digest = hmac.new(
        auth_token.encode("utf-8"),
        (url + nonce).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def validate_signature(auth_token: str, headers: Mapping[str, str], url: str) -> bool:
    signature = headers.get(SIGNATURE_HEADER)
    nonce = headers.get(NONCE_HEADER)
    if not signature or not nonce:
        return False
    expected = compute_signature(auth_token, url, nonce)
    return hmac.compare_digest(expected, signature)