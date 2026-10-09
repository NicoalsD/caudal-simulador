"""Shared pytest and Hypothesis configuration for the simulator."""

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hypothesis import settings

# A simulated year can exceed the default 200 ms deadline per example.
settings.register_profile("caudal", deadline=None)
settings.load_profile("caudal")


@pytest.fixture
def private_key_path(tmp_path: Path) -> Path:
    """A throwaway Ed25519 private key in PEM, created per test. Never a real key."""
    key = Ed25519PrivateKey.generate()
    path = tmp_path / "keys" / "ed25519-private.pem"
    path.parent.mkdir(parents=True)
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return path
