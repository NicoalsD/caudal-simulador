"""Ed25519 signing of import manifests: verifiable, encoded like the protocol, no key leaks."""

import base64
import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from pydantic import SecretStr

from caudal_sim.backfill import MANIFEST_SUFFIX, BackfillOptions, ImportKind, run_backfill
from caudal_sim.builder import load_scenario
from caudal_sim.config import SimulatorSettings
from caudal_sim.signing import (
    SIGNATURE_SUFFIX,
    SigningKeyError,
    load_private_key,
    public_key_fingerprint,
    sign_bytes,
)
from caudal_sim.terrain import run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
BASE_URL = "http://api.test"
SLUG = "guaitarilla-demo"
PAYLOAD = b'{"kind": "readings"}\n'
BASE64URL_ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
ED25519_SIGNATURE_BYTES = 64
FINGERPRINT_LENGTH = 64


def test_signature_verifies_with_the_public_key_and_uses_base64url_without_padding() -> None:
    key = Ed25519PrivateKey.generate()

    encoded = sign_bytes(PAYLOAD, key)
    padded = encoded + "=" * (-len(encoded) % 4)
    signature = base64.urlsafe_b64decode(padded)

    key.public_key().verify(signature, PAYLOAD)  # raises if invalid
    assert len(signature) == ED25519_SIGNATURE_BYTES
    assert set(encoded) <= BASE64URL_ALPHABET
    assert "=" not in encoded


def test_fingerprint_is_sha256_of_the_raw_public_key() -> None:
    key = Ed25519PrivateKey.generate()
    raw_public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )

    fingerprint = public_key_fingerprint(key)

    assert fingerprint == hashlib.sha256(raw_public).hexdigest()
    assert len(fingerprint) == FINGERPRINT_LENGTH


def test_missing_key_file_is_reported_without_reading_any_secret(tmp_path: Path) -> None:
    with pytest.raises(SigningKeyError) as caught:
        load_private_key(tmp_path / "keys" / "absent.pem")

    assert "No se encontró la clave privada" in caught.value.message


def test_non_pem_content_is_rejected_without_echoing_it(tmp_path: Path) -> None:
    path = tmp_path / "bad.pem"
    path.write_text("not-a-key-material-marker", encoding="utf-8")

    with pytest.raises(SigningKeyError) as caught:
        load_private_key(path)

    assert "not-a-key-material-marker" not in caught.value.message


def test_non_ed25519_key_is_rejected(tmp_path: Path) -> None:
    rsa_key = generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "rsa.pem"
    path.write_bytes(
        rsa_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    with pytest.raises(SigningKeyError) as caught:
        load_private_key(path)

    assert "no es Ed25519" in caught.value.message


def _settings(private_key_path: Path) -> SimulatorSettings:
    return SimulatorSettings(
        _env_file=None,  # type: ignore[call-arg]
        api_base_url=BASE_URL,
        api_username="project.team",
        api_password=SecretStr("contraseña-de-prueba-larga"),
        demo_aqueduct_slug=SLUG,
        aqueduct_id=UUID("0190f3a2-0000-7000-8000-0000000000bb"),
        tank_id=UUID("0190f3a2-2222-7000-8000-000000000001"),
        private_key_path=private_key_path,
    )


def _demo_router(router: respx.MockRouter) -> None:
    router.get(f"/api/v1/public/{SLUG}/schedule").respond(
        200, json={"aqueduct": {"name": "Demo", "is_demo": True}}
    )
    router.post("/api/v1/auth/login").respond(200, json={"access_token": "token-de-prueba"})


def test_real_run_writes_a_signed_manifest_without_key_material(
    private_key_path: Path, tmp_path: Path
) -> None:
    scenario = load_scenario(NORMAL_YAML)
    run = run_simulation(scenario, 1, 5)
    manifest_dir = tmp_path / "imports"
    settings = _settings(private_key_path)
    key = load_private_key(private_key_path)

    with respx.mock(base_url=BASE_URL) as router:
        _demo_router(router)
        router.post("/api/v1/imports/readings").respond(
            201, json={"rows_accepted": 1, "rows_rejected": 0}
        )
        summary = run_backfill(
            ImportKind.READINGS,
            scenario,
            run,
            settings,
            BackfillOptions(dry_run=False, manifest_dir=manifest_dir),
        )

    assert summary.manifest_path == manifest_dir / f"readings{MANIFEST_SUFFIX}"
    manifest_bytes = summary.manifest_path.read_bytes()
    encoded = (
        summary.manifest_path.with_name(summary.manifest_path.name + SIGNATURE_SUFFIX)
        .read_text(encoding="ascii")
        .strip()
    )
    signature = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    key.public_key().verify(signature, manifest_bytes)
    manifest = json.loads(manifest_bytes)
    assert manifest["is_simulated"] is True
    assert manifest["signing_key_fingerprint"] == public_key_fingerprint(key)
    assert b"PRIVATE KEY" not in manifest_bytes


def test_missing_key_stops_a_real_run_before_any_import_request(
    tmp_path: Path,
) -> None:
    scenario = load_scenario(NORMAL_YAML)
    run = run_simulation(scenario, 1, 5)
    settings = _settings(tmp_path / "keys" / "absent.pem")

    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        _demo_router(router)
        imported = router.post("/api/v1/imports/readings").respond(201)

        with pytest.raises(SigningKeyError):
            run_backfill(
                ImportKind.READINGS,
                scenario,
                run,
                settings,
                BackfillOptions(dry_run=False, manifest_dir=tmp_path / "imports"),
            )

    assert not imported.called
    assert not (tmp_path / "imports").exists()


def test_dry_run_neither_reads_the_key_nor_writes_a_manifest(tmp_path: Path) -> None:
    scenario = load_scenario(NORMAL_YAML)
    run = run_simulation(scenario, 1, 5)

    run_backfill(
        ImportKind.READINGS,
        scenario,
        run,
        _settings(tmp_path / "keys" / "absent.pem"),
        BackfillOptions(dry_run=True, manifest_dir=tmp_path / "imports"),
    )

    assert not (tmp_path / "imports").exists()
