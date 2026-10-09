"""Backfill of shift executions: one row per shift, statuses and actual windows."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from pydantic import SecretStr
from typer.testing import CliRunner

from caudal_sim.backfill import ImportKind, run_backfill
from caudal_sim.builder import load_scenario
from caudal_sim.cli import app
from caudal_sim.config import SimulatorSettings
from caudal_sim.scenario import Scenario
from caudal_sim.shifts import ShiftOutcome
from caudal_sim.terrain import SimulationRun, run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
BASE_URL = "http://api.test"
SLUG = "guaitarilla-demo"
IMPORT_PATH = "/api/v1/imports/shift-executions"
SIMULATED_DAYS = 3
SEED = 11
ALLOWED_STATUSES = {outcome.value for outcome in ShiftOutcome}


def _settings() -> SimulatorSettings:
    return SimulatorSettings(
        _env_file=None,  # type: ignore[call-arg]
        api_base_url=BASE_URL,
        api_username="project.team",
        api_password=SecretStr("contraseña-de-prueba-larga"),
        demo_aqueduct_slug=SLUG,
        aqueduct_id=UUID("0190f3a2-0000-7000-8000-0000000000bb"),
        tank_id=UUID("0190f3a2-2222-7000-8000-000000000001"),
    )


def _accept_all(request: httpx.Request) -> httpx.Response:
    rows = json.loads(request.content)["rows"]
    return httpx.Response(
        201,
        json={"rows_received": len(rows), "rows_accepted": len(rows), "rows_rejected": 0},
    )


def _demo_router(router: respx.MockRouter) -> None:
    router.get(f"/api/v1/public/{SLUG}/schedule").respond(
        200, json={"aqueduct": {"name": "Demo", "is_demo": True}}
    )
    router.post("/api/v1/auth/login").respond(200, json={"access_token": "token-de-prueba"})


def _run() -> tuple[Scenario, SimulationRun]:
    scenario = load_scenario(NORMAL_YAML)
    return scenario, run_simulation(scenario, SIMULATED_DAYS, SEED)


def test_dry_run_has_one_row_per_observed_shift() -> None:
    scenario, run = _run()

    summary = run_backfill(ImportKind.SHIFT_EXECUTIONS, scenario, run, _settings(), dry_run=True)

    assert summary.rows_total == len(run.observed.shift_executions)
    assert summary.duplicates_skipped == 0


def test_real_run_sends_every_shift_with_a_contract_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario, run = _run()
    sent: list[dict[str, Any]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        sent.extend(json.loads(request.content)["rows"])
        return _accept_all(request)

    with respx.mock(base_url=BASE_URL) as router:
        _demo_router(router)
        router.post(IMPORT_PATH).mock(side_effect=capture)

        summary = run_backfill(
            ImportKind.SHIFT_EXECUTIONS, scenario, run, _settings(), dry_run=False
        )

    assert summary.rows_accepted == len(run.observed.shift_executions)
    assert {row["status"] for row in sent} <= ALLOWED_STATUSES
    for row in sent:
        assert (row["actual_start"] is None) == (row["status"] == ShiftOutcome.NOT_EXECUTED)


def test_cli_dry_run_for_shift_executions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAUDAL_SIM_API_BASE_URL", BASE_URL)
    monkeypatch.setenv("CAUDAL_SIM_API_USERNAME", "project.team")
    monkeypatch.setenv("CAUDAL_SIM_API_PASSWORD", "contraseña-de-prueba-larga")
    monkeypatch.setenv("CAUDAL_SIM_DEMO_AQUEDUCT_SLUG", SLUG)
    monkeypatch.setenv("CAUDAL_SIM_AQUEDUCT_ID", "0190f3a2-0000-7000-8000-0000000000bb")
    monkeypatch.setenv("CAUDAL_SIM_TANK_ID", "0190f3a2-2222-7000-8000-000000000001")

    result = CliRunner().invoke(app, ["backfill", "shift-executions", "--days", "2", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "No se envió nada" in result.output
