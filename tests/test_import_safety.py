"""Import safety: row counts per kind, and nothing is sent to a target that is not the demo."""

import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import respx
from pydantic import SecretStr

from caudal_sim.api_client import ApiError, encode_json
from caudal_sim.backfill import (
    MAX_IMPORT_BODY_BYTES,
    MAX_IMPORT_ROWS,
    BackfillOptions,
    ImportKind,
    run_backfill,
)
from caudal_sim.builder import load_scenario
from caudal_sim.config import SimulatorSettings
from caudal_sim.demo_guard import NonDemoTargetError
from caudal_sim.scenario import Scenario
from caudal_sim.terrain import SimulationRun, run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
BASE_URL = "http://api.test"
SLUG = "guaitarilla-demo"
IMPORT_PATHS = {
    ImportKind.READINGS: "/api/v1/imports/readings",
    ImportKind.SHIFT_EXECUTIONS: "/api/v1/imports/shift-executions",
    ImportKind.INCIDENTS: "/api/v1/imports/incidents",
}
SIMULATED_DAYS = 365
SEED = 21
HTTP_FORBIDDEN = 403


@pytest.fixture
def simulated() -> tuple[Scenario, SimulationRun]:
    scenario = load_scenario(NORMAL_YAML)
    run = run_simulation(scenario, SIMULATED_DAYS, SEED)
    # Each kind must have rows, otherwise the counts below would prove nothing.
    assert run.observed.readings
    assert run.observed.shift_executions
    assert run.observed.damage_reports
    return scenario, run


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


def _expected_rows(kind: ImportKind, run: SimulationRun) -> int:
    if kind is ImportKind.READINGS:
        return sum(1 for reading in run.observed.readings if not reading.is_duplicate)
    if kind is ImportKind.SHIFT_EXECUTIONS:
        return len(run.observed.shift_executions)
    return len(run.observed.damage_reports)


@pytest.mark.parametrize("kind", list(ImportKind))
def test_rows_sent_match_the_observed_records_of_each_kind(
    kind: ImportKind,
    simulated: tuple[Scenario, SimulationRun],
    private_key_path: Path,
) -> None:
    scenario, run = simulated
    sent: list[int] = []

    def count(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(len(body["rows"]))
        assert len(encode_json(body)) <= MAX_IMPORT_BODY_BYTES
        assert len(body["rows"]) <= MAX_IMPORT_ROWS
        return httpx.Response(201, json={"rows_accepted": len(body["rows"]), "rows_rejected": 0})

    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"/api/v1/public/{SLUG}/schedule").respond(
            200, json={"aqueduct": {"name": "Demo", "is_demo": True}}
        )
        router.post("/api/v1/auth/login").respond(200, json={"access_token": "token"})
        router.post(IMPORT_PATHS[kind]).mock(side_effect=count)

        summary = run_backfill(
            kind, scenario, run, _settings(private_key_path), BackfillOptions(dry_run=False)
        )

    assert sum(sent) == _expected_rows(kind, run) == summary.rows_total
    assert summary.rows_accepted == summary.rows_total
    assert len(sent) == summary.batches


@pytest.mark.parametrize("kind", list(ImportKind))
def test_non_demo_target_sends_no_import_and_no_credentials(
    kind: ImportKind,
    simulated: tuple[Scenario, SimulationRun],
    private_key_path: Path,
) -> None:
    scenario, run = simulated
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        router.get(f"/api/v1/public/{SLUG}/schedule").respond(
            200, json={"aqueduct": {"name": "Real", "is_demo": False}}
        )
        login = router.post("/api/v1/auth/login").respond(200, json={"access_token": "t"})
        imported = router.post(IMPORT_PATHS[kind]).respond(201)

        with pytest.raises(NonDemoTargetError):
            run_backfill(
                kind, scenario, run, _settings(private_key_path), BackfillOptions(dry_run=False)
            )

    assert not login.called
    assert not imported.called


def test_backend_demo_only_refusal_stops_the_remaining_batches(
    simulated: tuple[Scenario, SimulationRun], private_key_path: Path
) -> None:
    scenario, run = simulated
    refusal = {
        "error": {
            "code": "DEMO_ONLY",
            "message": "Esta operación solo aplica al acueducto de demostración.",
        }
    }
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        router.get(f"/api/v1/public/{SLUG}/schedule").respond(
            200, json={"aqueduct": {"name": "Demo", "is_demo": True}}
        )
        router.post("/api/v1/auth/login").respond(200, json={"access_token": "t"})
        imported = router.post(IMPORT_PATHS[ImportKind.READINGS]).respond(
            HTTP_FORBIDDEN, json=refusal
        )

        with pytest.raises(ApiError) as caught:
            run_backfill(
                ImportKind.READINGS,
                scenario,
                run,
                _settings(private_key_path),
                BackfillOptions(dry_run=False),
            )

    assert caught.value.code == "DEMO_ONLY"
    assert imported.call_count == 1


def test_unconfirmed_demo_target_sends_nothing(
    simulated: tuple[Scenario, SimulationRun], private_key_path: Path
) -> None:
    scenario, run = simulated
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        router.get(f"/api/v1/public/{SLUG}/schedule").respond(
            404, json={"error": {"code": "NOT_FOUND", "message": "No encontramos ese recurso."}}
        )
        imported = router.post(IMPORT_PATHS[ImportKind.SHIFT_EXECUTIONS]).respond(201)

        with pytest.raises(NonDemoTargetError):
            run_backfill(
                ImportKind.SHIFT_EXECUTIONS,
                scenario,
                run,
                _settings(private_key_path),
                BackfillOptions(dry_run=False),
            )

    assert not imported.called
