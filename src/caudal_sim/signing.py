"""Ed25519 signature of import manifests, following the device protocol encoding.

The private key is a PEM file kept in `keys/` (git-ignored). It is read only to sign and is
never printed, logged or written to a manifest. Signatures and public-key fingerprints use
the same encoding as `Protocolo-de-dispositivos.md`: base64url without padding for the
signature, and SHA-256 of the raw 32-byte public key in lowercase hex for the fingerprint.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

BASE64URL_PADDING = b"="
SIGNATURE_SUFFIX = ".sig"


class SigningKeyError(Exception):
    """The signing key is missing or is not a usable Ed25519 private key."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def load_private_key(path: Path) -> Ed25519PrivateKey:
    """Reads the PEM private key. The error never includes the key material."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise SigningKeyError(
            f"No se encontró la clave privada en {path}. Revisa CAUDAL_SIM_PRIVATE_KEY_PATH."
        ) from error
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except ValueError as error:
        raise SigningKeyError(
            f"La clave en {path} no es una clave PEM sin contraseña válida."
        ) from error
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningKeyError(f"La clave en {path} no es Ed25519.")
    return key


def public_key_fingerprint(key: Ed25519PrivateKey) -> str:
    """SHA-256 of the raw public key bytes, in lowercase hex (64 characters)."""
    raw_public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw_public).hexdigest()


def sign_bytes(data: bytes, key: Ed25519PrivateKey) -> str:
    """Ed25519 signature of `data`, base64url without padding."""
    signature = key.sign(data)
    return base64.urlsafe_b64encode(signature).rstrip(BASE64URL_PADDING).decode("ascii")
