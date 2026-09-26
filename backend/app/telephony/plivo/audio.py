import audioop
import base64
import binascii

_SUPPORTED_ENCODINGS = {"mulaw", "pcmu", "audio/x-mulaw"}


class PlivoAudioDecodingError(Exception):
    pass


def is_supported_encoding(encoding: str | None) -> bool:
    return bool(encoding) and encoding.strip().lower() in _SUPPORTED_ENCODINGS


def decode_media_payload(payload_b64: str) -> bytes:
    """Decode a Plivo "media" event payload (base64-encoded 8-bit mu-law)
    into 16-bit signed linear PCM bytes."""
    if not payload_b64:
        raise PlivoAudioDecodingError("media payload is empty.")

    try:
        mulaw_bytes = base64.b64decode(payload_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PlivoAudioDecodingError("media payload is not valid base64.") from exc

    if not mulaw_bytes:
        raise PlivoAudioDecodingError("decoded media payload is empty.")

    try:
        return audioop.ulaw2lin(mulaw_bytes, 2)
    except audioop.error as exc:
        raise PlivoAudioDecodingError(
            "media payload could not be decoded as mu-law audio."
        ) from exc