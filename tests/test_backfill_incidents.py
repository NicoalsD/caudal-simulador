"""Backfill of simulated incidents: one row per damage report, with a valid sector."""

import json
from pathlib import Path
from uuid import UUID

import httpx
import respx
from pydantic import SecretStr

from caudal_sim.api_payload import ApiPayloadAdapter, ImportContext
from caudal_sim.backfill import BackfillOptions, ImportKind, run_backfill
from caudal_sim.builder import load_scenario
from caudal_sim.config import SimulatorSettings
from caudal_sim.terrain import DAMAGE_CATEGORY_LEAK, DamageReport, run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
BASE_URL = "http://api.test"
SLUG = "guaitarilla-demo"
IMPORT_PATH = "/api/v1/imports/incidents"
AQUEDUCT_ID = UUID("0190f3a2-0000-7000-8000-0000000000bb")
TANK_ID = UUID("0190f3a2-2222-7000-8000-000000000001")
SIMULATED_DAYS = 120
SEED = 3


def _settings(private_key_path: Path) -> SimulatorSettings:
    return SimulatorSettings(
        _env_file=None,  # type: ignore[call-arg]
        api_base_url=BASE_URL,
        api_username="project.team",
        api_password=SecretStr("contraseña-de-prueba-larga"),
        demo_aqueduct_slug=SLUG,
        aqueduct_id=AQUEDUCT_ID,
        tank_id=TANK_ID,
        private_key_path=private_key_path,
    )


def test_each_damage_report_becomes_one_incident_row_with_leak_category(
    private_key_path: Path,
) -> None:
    scenario = load_scenario(NORMAL_YAML)
    run = run_simulation(scenario, SIMULATED_DAYS, SEED)

    summary = run_backfill(
        ImportKind.INCIDENTS,
        scenario,
        run,
        _settings(private_key_path),
        BackfillOptions(dry_run=True),
    )

    assert summary.rows_total == len(run.observed.damage_reports)
    assert all(report.category == DAMAGE_CATEGORY_LEAK for report in run.observed.damage_reports)


def test_real_run_posts_incidents_with_known_sector_ids(private_key_path: Path) -> None:
    scenario = load_scenario(NORMAL_YAML)
    run = run_simulation(scenario, SIMULATED_DAYS, SEED)
    context = ImportContext(
        aqueduct_id=AQUEDUCT_ID,
        tank_id=TANK_ID,
        start=run.start,
        sector_slugs=tuple(sector.id for sector in scenario.sectors),
    )
    known_sector_ids = _sector_ids(context)
    sent: list[dict[str, object]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        rows = json.loads(request.content)["rows"]
        sent.extend(rows)
        return httpx.Response(201, json={"rows_accepted": len(rows), "rows_rejected": 0})

    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"/api/v1/public/{SLUG}/schedule").respond(
            200, json={"aqueduct": {"name": "Demo", "is_demo": True}}
        )
        router.post("/api/v1/auth/login").respond(200, json={"access_token": "token-de-prueba"})
        router.post(IMPORT_PATH).mock(side_effect=capture)

        summary = run_backfill(
            ImportKind.INCIDENTS,
            scenario,
            run,
            _settings(private_key_path),
            BackfillOptions(dry_run=False),
        )

    assert summary.rows_accepted == len(run.observed.damage_reports)
    assert {row["sector_id"] for row in sent} <= known_sector_ids


def _sector_ids(context: ImportContext) -> set[str]:
    """Every sector identifier the adapter can produce for this aqueduct."""
    adapter = ApiPayloadAdapter(context)
    reports = [
        DamageReport(report_id=index, day_index=0, category=DAMAGE_CATEGORY_LEAK)
        for index in range(len(context.sector_slugs))
    ]
    return {str(adapter.incident_row(report)["sector_id"]) for report in reports}
