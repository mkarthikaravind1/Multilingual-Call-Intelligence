"""Encrypting what is copied off the server: transcripts and database
backups (recordings are encrypted where they are made, see
recording_archive).

AES-256-GCM under ARCHIVE_ENCRYPTION_KEY, a 32-byte key in base64 like the
recording key. A file is encrypted in pieces so that a backup of any size
never has to fit in memory; each piece is bound to its place, to the file's
name and to whether it is the last, so pieces cannot be dropped, reordered
or moved to another file without the decryption failing.
"""

import io
import os
import struct
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MAGIC = b"MCIENC1\n"
_NONCE_PREFIX_BYTES = 8
_PIECE_BYTES = 1024 * 1024
_LENGTH = struct.Struct(">I")
_COUNTER = struct.Struct(">I")


class DecryptionError(Exception):
    """The file is not ours, was changed, or the key is another one."""


def _aad(name: str, last: bool) -> bytes:
    return name.encode() + (b"\x01" if last else b"\x00")


def encrypt_stream(source: BinaryIO, out: BinaryIO, key: bytes, name: str) -> None:
    """name: what the file is (bound into it, and needed to decrypt)."""
    cipher = AESGCM(key)
    prefix = os.urandom(_NONCE_PREFIX_BYTES)
    out.write(_MAGIC + prefix)
    counter = 0
    piece = source.read(_PIECE_BYTES)
    while True:
        following = source.read(_PIECE_BYTES)
        last = not following
        sealed = cipher.encrypt(prefix + _COUNTER.pack(counter), piece, _aad(name, last))
        out.write(_LENGTH.pack(len(sealed)) + sealed)
        if last:
            return
        piece = following
        counter += 1


def decrypt_stream(source: BinaryIO, out: BinaryIO, key: bytes, name: str) -> None:
    cipher = AESGCM(key)
    header = source.read(len(_MAGIC) + _NONCE_PREFIX_BYTES)
    if len(header) != len(_MAGIC) + _NONCE_PREFIX_BYTES or not header.startswith(_MAGIC):
        raise DecryptionError("This is not an encrypted archive file.")
    prefix = header[len(_MAGIC) :]
    counter = 0
    length = source.read(_LENGTH.size)
    while True:
        if len(length) != _LENGTH.size:
            raise DecryptionError("The file is cut short.")
        sealed = source.read(_LENGTH.unpack(length)[0])
        length = source.read(_LENGTH.size)
        last = not length
        try:
            out.write(cipher.decrypt(prefix + _COUNTER.pack(counter), sealed, _aad(name, last)))
        except InvalidTag as exc:
            raise DecryptionError(
                "The file cannot be decrypted: the key is another one, or the file was "
                "changed or cut short."
            ) from exc
        if last:
            return
        counter += 1


def encrypt_file(source: str | Path, target: str | Path, key: bytes, name: str) -> None:
    with open(source, "rb") as plain, open(target, "wb") as out:
        encrypt_stream(plain, out, key, name)


def decrypt_file(source: str | Path, target: str | Path, key: bytes, name: str) -> None:
    with open(source, "rb") as sealed, open(target, "wb") as out:
        decrypt_stream(sealed, out, key, name)


def encrypt_bytes(data: bytes, key: bytes, name: str) -> bytes:
    out = io.BytesIO()
    encrypt_stream(io.BytesIO(data), out, key, name)
    return out.getvalue()


def decrypt_bytes(data: bytes, key: bytes, name: str) -> bytes:
    out = io.BytesIO()
    decrypt_stream(io.BytesIO(data), out, key, name)
    return out.getvalue()
