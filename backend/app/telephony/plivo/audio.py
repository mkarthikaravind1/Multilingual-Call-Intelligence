import audioop
import base64
import binascii

MULAW = "mulaw"
L16 = "l16"

_ENCODINGS = {
    "mulaw": MULAW,
    "pcmu": MULAW,
    "audio/x-mulaw": MULAW,
    "l16": L16,
    "linear16": L16,
    "audio/x-l16": L16,
}


class PlivoAudioDecodingError(Exception):
    pass


def normalize_encoding(encoding: str | None) -> str | None:
    """MULAW or L16 for a supported Plivo stream encoding, else None."""
    if not encoding:
        return None
    return _ENCODINGS.get(encoding.strip().lower())


def is_supported_encoding(encoding: str | None) -> bool:
    return normalize_encoding(encoding) is not None


def decode_media_payload(payload_b64: str, encoding: str = MULAW) -> bytes:
    """Decode a Plivo "media" event payload (base64-encoded 8-bit mu-law, or
    16-bit linear PCM for L16 streams) into 16-bit signed linear PCM bytes."""
    if not payload_b64:
        raise PlivoAudioDecodingError("media payload is empty.")

    try:
        raw = base64.b64decode(payload_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PlivoAudioDecodingError("media payload is not valid base64.") from exc

    if not raw:
        raise PlivoAudioDecodingError("decoded media payload is empty.")

    if encoding == L16:
        # Raw little-endian 16-bit samples: already the PCM we work in.
        if len(raw) % 2:
            raise PlivoAudioDecodingError("L16 media payload has an odd number of bytes.")
        return raw

    try:
        return audioop.ulaw2lin(raw, 2)
    except audioop.error as exc:
        raise PlivoAudioDecodingError(
            "media payload could not be decoded as mu-law audio."
        ) from exc
