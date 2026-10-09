"""ApiPayloadAdapter tests: contract field names, identifiers, timestamps and enums."""

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from caudal_sim.api_payload import (
    DAMAGE_DESCRIPTION,
    ApiPayloadAdapter,
    ImportContext,
    ImportPayloadTarget,
)
from caudal_sim.readings import TransmittedReading
from caudal_sim.shifts import ShiftExecution, ShiftOutcome
from caudal_sim.terrain import DAMAGE_CATEGORY_LEAK, DamageReport

AQUEDUCT_ID = UUID("0190f3a2-0000-7000-8000-0000000000bb")
TANK_ID = UUID("0190f3a2-2222-7000-8000-000000000001")
START = datetime(2026, 1, 1, tzinfo=ZoneInfo("America/Bogota"))
SECTORS = ("sector-alto", "sector-bajo")
ROUNDED_GAUGE = 3.46
UUID_V5 = 5
READING_ROW_KEYS = {
    "id",
    "tank_id",
    "gauge_value",
    "water_appearance_code",
    "damage_noticed",
    "note",
    "observed_at",
}
SHIFT_ROW_KEYS = {"schedule_item_id", "status", "actual_start", "actual_end", "note"}
INCIDENT_ROW_KEYS = {"category_code", "sector_id", "description", "location_hint", "reported_at"}


@pytest.fixture
def adapter() -> ApiPayloadAdapter:
    context = ImportContext(
        aqueduct_id=AQUEDUCT_ID, tank_id=TANK_ID, start=START, sector_slugs=SECTORS
    )
    return ApiPayloadAdapter(context)


def test_adapter_implements_the_import_payload_target(adapter: ApiPayloadAdapter) -> None:
    assert isinstance(adapter, ImportPayloadTarget)


def test_reading_row_uses_snake_case_contract_fields(adapter: ApiPayloadAdapter) -> None:
    row = adapter.reading_row(TransmittedReading(7, 25, 26, 3.456, False, False))

    assert set(row) == READING_ROW_KEYS
    assert row["tank_id"] == str(TANK_ID)
    assert row["gauge_value"] == ROUNDED_GAUGE
    assert row["damage_noticed"] is False


def test_reading_observed_at_is_iso_with_the_aqueduct_offset(adapter: ApiPayloadAdapter) -> None:
    row = adapter.reading_row(TransmittedReading(7, 25, 26, 3.4, False, False))

    assert row["observed_at"] == "2026-01-02T01:00:00-05:00"


def test_reading_identifier_is_stable_and_unique_per_reading(adapter: ApiPayloadAdapter) -> None:
    first = adapter.reading_row(TransmittedReading(1, 0, 0, 3.0, False, False))
    again = adapter.reading_row(TransmittedReading(1, 0, 0, 3.0, False, False))
    other = adapter.reading_row(TransmittedReading(2, 0, 0, 3.0, False, False))

    assert first["id"] == again["id"]
    assert first["id"] != other["id"]
    assert UUID(first["id"]).version == UUID_V5


def test_shift_row_has_actual_window_and_status(adapter: ApiPayloadAdapter) -> None:
    shift = ShiftExecution(
        day_index=1,
        sector_id="sector-alto",
        start_hour=6,
        end_hour=10,
        outcome=ShiftOutcome.PARTIAL,
        open_hours=2,
    )

    row = adapter.shift_execution_row(shift)

    assert set(row) == SHIFT_ROW_KEYS
    assert row["status"] == "PARTIAL"
    assert row["actual_start"] == "2026-01-02T06:00:00-05:00"
    assert row["actual_end"] == "2026-01-02T08:00:00-05:00"


def test_shift_not_executed_has_no_actual_times(adapter: ApiPayloadAdapter) -> None:
    shift = ShiftExecution(
        day_index=0,
        sector_id="sector-bajo",
        start_hour=14,
        end_hour=18,
        outcome=ShiftOutcome.NOT_EXECUTED,
        open_hours=0,
    )

    row = adapter.shift_execution_row(shift)

    assert row["status"] == "NOT_EXECUTED"
    assert row["actual_start"] is None
    assert row["actual_end"] is None


def test_incident_row_maps_category_and_marks_simulated_text(adapter: ApiPayloadAdapter) -> None:
    report = DamageReport(report_id=3, day_index=4, category=DAMAGE_CATEGORY_LEAK)

    row = adapter.incident_row(report)

    assert set(row) == INCIDENT_ROW_KEYS
    assert row["category_code"] == DAMAGE_CATEGORY_LEAK
    assert row["description"] == DAMAGE_DESCRIPTION
    assert row["reported_at"] == "2026-01-05T12:00:00-05:00"


def test_incident_sector_is_assigned_in_turn_and_is_stable(adapter: ApiPayloadAdapter) -> None:
    first = adapter.incident_row(DamageReport(0, 0, DAMAGE_CATEGORY_LEAK))
    second = adapter.incident_row(DamageReport(1, 0, DAMAGE_CATEGORY_LEAK))
    third = adapter.incident_row(DamageReport(2, 0, DAMAGE_CATEGORY_LEAK))

    assert first["sector_id"] == third["sector_id"]
    assert first["sector_id"] != second["sector_id"]
