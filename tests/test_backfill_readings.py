"""Backfill of readings: batch limits, dry run, real run against a mocked API."""

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from pydantic import SecretStr
from typer.testing import CliRunner

from caudal_sim.api_client import encode_json
from caudal_sim.backfill import (
    MAX_IMPORT_BODY_BYTES,
    MAX_IMPORT_ROWS,
    BatchMetadata,
    ImportKind,
    build_batches,
    run_backfill,
)
from caudal_sim.builder import load_scenario
from caudal_sim.cli import app
from caudal_sim.config import SimulatorSettings
from caudal_sim.demo_guard import NonDemoTargetError
from caudal_sim.terrain import run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
BASE_URL = "http://api.test"
SLUG = "guaitarilla-demo"
AQUEDUCT_ID = UUID("0190f3a2-0000-7000-8000-0000000000bb")
TANK_ID = UUID("0190f3a2-2222-7000-8000-000000000001")
IMPORT_PATH = "/api/v1/imports/readings"
SIMULATED_DAYS = 2
SEED = 7
PASSWORD = "contraseña-de-prueba-larga"
TOKEN = "token-de-prueba"
NOTE_CHARACTERS = 500
HEX_DIGITS = set("0123456789abcdef")
METADATA = BatchMetadata(aqueduct_id=AQUEDUCT_ID, scenario_name="normal-year", seed=SEED)


def _settings() -> SimulatorSettings:
    return SimulatorSettings(
        _env_file=None,  # type: ignore[call-arg]
        api_base_url=BASE_URL,
        api_username="project.team",
        api_password=SecretStr(PASSWORD),
        demo_aqueduct_slug=SLUG,
        aqueduct_id=AQUEDUCT_ID,
        tank_id=TANK_ID,
    )


def _row(index: int, note_size: int = 0) -> dict[str, Any]:
    return {"id": str(index), "note": "x" * note_size}


def _run_and_scenario() -> tuple[Any, Any]:
    scenario = load_scenario(NORMAL_YAML)
    return scenario, run_simulation(scenario, SIMULATED_DAYS, SEED)


def _demo_router(router: respx.MockRouter, *, is_demo: bool = True) -> None:
    router.get(f"/api/v1/public/{SLUG}/schedule").respond(
        200, json={"aqueduct": {"name": "Demo", "is_demo": is_demo}, "items": []}
    )
    router.post("/api/v1/auth/login").respond(200, json={"access_token": TOKEN})


def _accept_all(request: httpx.Request) -> httpx.Response:
    rows = json.loads(request.content)["rows"]
    return httpx.Response(
        201,
        json={
            "rows_received": len(rows),
            "rows_accepted": len(rows),
            "rows_rejected": 0,
            "rejections": [],
        },
    )


def test_batches_never_exceed_the_row_limit() -> None:
    rows = [_row(index) for index in range(MAX_IMPORT_ROWS + 1)]

    batches = build_batches(IMPORT_PATH, rows, METADATA)

    assert [batch.row_count for batch in batches] == [MAX_IMPORT_ROWS, 1]


def test_batches_never_exceed_the_body_byte_limit() -> None:
    rows = [_row(index, note_size=NOTE_CHARACTERS) for index in range(4000)]

    batches = build_batches(IMPORT_PATH, rows, METADATA)

    assert len(batches) > 1
    assert sum(batch.row_count for batch in batches) == len(rows)
    for batch in batches:
        assert len(encode_json(batch.body)) <= MAX_IMPORT_BODY_BYTES


def test_each_batch_hash_is_the_sha256_of_its_own_rows() -> None:
    rows = [_row(index) for index in range(3)]

    (batch,) = build_batches(IMPORT_PATH, rows, METADATA)

    expected = hashlib.sha256(encode_json({"rows": rows})).hexdigest()
    assert batch.file_sha256 == expected
    assert len(batch.file_sha256) == 64
    assert set(batch.file_sha256) <= HEX_DIGITS


def test_dry_run_counts_batches_and_never_contacts_the_api() -> None:
    scenario, run = _run_and_scenario()
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        summary = run_backfill(ImportKind.READINGS, scenario, run, _settings(), dry_run=True)

    assert router.calls.call_count == 0
    assert summary.dry_run is True
    assert summary.rows_accepted == 0
    assert summary.rows_total == len(run.observed.readings) - summary.duplicates_skipped


def test_duplicate_transmissions_are_skipped_and_counted() -> None:
    scenario, run = _run_and_scenario()
    duplicates = sum(1 for reading in run.observed.readings if reading.is_duplicate)

    summary = run_backfill(ImportKind.READINGS, scenario, run, _settings(), dry_run=True)

    assert summary.duplicates_skipped == duplicates


def test_real_run_sends_every_row_and_reports_what_the_api_accepted() -> None:
    scenario, run = _run_and_scenario()
    with respx.mock(base_url=BASE_URL) as router:
        _demo_router(router)
        router.post(IMPORT_PATH).mock(side_effect=_accept_all)

        summary = run_backfill(ImportKind.READINGS, scenario, run, _settings(), dry_run=False)

    assert summary.rows_accepted == summary.rows_total
    assert summary.rows_rejected == 0
    assert summary.batches >= 1


def test_real_run_is_refused_for_a_real_aqueduct_and_sends_nothing() -> None:
    scenario, run = _run_and_scenario()
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        _demo_router(router, is_demo=False)
        imported = router.post(IMPORT_PATH).respond(201)

        with pytest.raises(NonDemoTargetError):
            run_backfill(ImportKind.READINGS, scenario, run, _settings(), dry_run=False)

    assert not imported.called


def test_cli_dry_run_prints_counts_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_environment(monkeypatch)
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        result = CliRunner().invoke(app, ["backfill", "readings", "--days", "1", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "No se envió nada" in result.output
    assert router.calls.call_count == 0


def test_cli_reports_missing_configuration_in_spanish(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("API_BASE_URL", "API_USERNAME", "API_PASSWORD", "DEMO_AQUEDUCT_SLUG"):
        monkeypatch.delenv(f"CAUDAL_SIM_{name}", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here, so only the environment counts

    result = CliRunner().invoke(
        app, ["backfill", "readings", "--scenario", str(NORMAL_YAML), "--dry-run"]
    )

    assert result.exit_code == 2
    assert "CAUDAL_SIM_API_USERNAME" in result.output


def test_cli_real_run_aborts_with_spanish_message_for_a_real_aqueduct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_environment(monkeypatch)
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        _demo_router(router, is_demo=False)
        result = CliRunner().invoke(app, ["backfill", "readings", "--days", "1"])

    assert result.exit_code == 3
    assert "no es el acueducto de demostración" in result.output


def _set_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAUDAL_SIM_API_BASE_URL", BASE_URL)
    monkeypatch.setenv("CAUDAL_SIM_API_USERNAME", "project.team")
    monkeypatch.setenv("CAUDAL_SIM_API_PASSWORD", PASSWORD)
    monkeypatch.setenv("CAUDAL_SIM_DEMO_AQUEDUCT_SLUG", SLUG)
    monkeypatch.setenv("CAUDAL_SIM_AQUEDUCT_ID", str(AQUEDUCT_ID))
    monkeypatch.setenv("CAUDAL_SIM_TANK_ID", str(TANK_ID))
