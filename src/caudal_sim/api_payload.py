"""Adapter from simulator records to the JSON bodies of the CAUDAL import API.

The simulator works with its own records (hours since the start, sector slugs, a
numeric gauge). The API expects snake_case JSON, UUIDs, ISO-8601 timestamps with
offset and the enums of the contract. This module converts one into the other so the
domain never knows the wire format.

Identifiers are derived with UUID version 5 from the aqueduct, so a re-run produces the
same identifiers. The contract requires UUIDs that exist in the backend, and the backend
does not yet expose a mapping from simulator slugs to its identifiers; this derivation is
a placeholder until it does.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from caudal_sim.readings import TransmittedReading
from caudal_sim.shifts import ShiftExecution, ShiftOutcome
from caudal_sim.terrain import DamageReport

# Label that scopes every identifier the simulator derives. Fixed so that re-runs are identical.
ID_LABEL = "caudal-sim"
GAUGE_DECIMALS = 2
# Observed water appearance is not modelled by the simulator; the operator's usual code.
DEFAULT_WATER_APPEARANCE = "NORMAL"
DEFAULT_NOTE = ""
DAMAGE_DESCRIPTION = "Reporte simulado de fuga en la red. Dato simulado."
DAMAGE_LOCATION_HINT = "Ubicación simulada"
# Hour of the day at which a simulated damage report is registered.
REPORT_HOUR = 12
HOURS_PER_DAY = 24


@dataclass(frozen=True)
class ImportContext:
    """Where the records belong: the aqueduct, its tank, the local start and its sectors."""

    aqueduct_id: UUID
    tank_id: UUID
    start: datetime
    sector_slugs: tuple[str, ...]


class ImportPayloadTarget(ABC):
    """Target interface: the bodies the import endpoints expect, one per row type."""

    @abstractmethod
    def reading_row(self, reading: TransmittedReading) -> dict[str, Any]:
        """Body of one row for `POST /api/v1/imports/readings`."""

    @abstractmethod
    def shift_execution_row(self, shift: ShiftExecution) -> dict[str, Any]:
        """Body of one row for `POST /api/v1/imports/shift-executions`."""

    @abstractmethod
    def incident_row(self, report: DamageReport) -> dict[str, Any]:
        """Body of one row for `POST /api/v1/imports/incidents`."""


class ApiPayloadAdapter(ImportPayloadTarget):
    """Converts simulator records into the snake_case rows of the import API.

    @pattern P06 Adapter
    """

    def __init__(self, context: ImportContext) -> None:
        self._context = context

    def reading_row(self, reading: TransmittedReading) -> dict[str, Any]:
        """Maps a reading to the contract fields; `source` is fixed by the backend."""
        return {
            "id": str(self._derive("reading", str(reading.reading_id))),
            "tank_id": str(self._context.tank_id),
            "gauge_value": round(reading.gauge_m, GAUGE_DECIMALS),
            "water_appearance_code": DEFAULT_WATER_APPEARANCE,
            "damage_noticed": False,
            "note": DEFAULT_NOTE,
            "observed_at": self._at(hours=reading.observed_hour_index).isoformat(),
        }

    def shift_execution_row(self, shift: ShiftExecution) -> dict[str, Any]:
        """Maps a shift outcome. A shift that was not executed has no actual times."""
        item_id = self._derive("shift", f"{shift.day_index}:{shift.sector_id}:{shift.start_hour}")
        if shift.outcome is ShiftOutcome.NOT_EXECUTED:
            actual_start: str | None = None
            actual_end: str | None = None
        else:
            start = self._at(days=shift.day_index, hours=shift.start_hour)
            actual_start = start.isoformat()
            actual_end = (start + timedelta(hours=shift.open_hours)).isoformat()
        return {
            "schedule_item_id": str(item_id),
            "status": shift.outcome.value,
            "actual_start": actual_start,
            "actual_end": actual_end,
            "note": DEFAULT_NOTE,
        }

    def incident_row(self, report: DamageReport) -> dict[str, Any]:
        """Maps a damage report. The report has no sector, so sectors are assigned in turn."""
        slugs = self._context.sector_slugs
        slug = slugs[report.report_id % len(slugs)]
        return {
            "category_code": report.category,
            "sector_id": str(self._sector_id(slug)),
            "description": DAMAGE_DESCRIPTION,
            "location_hint": DAMAGE_LOCATION_HINT,
            "reported_at": self._at(days=report.day_index, hours=REPORT_HOUR).isoformat(),
        }

    def _at(self, *, days: int = 0, hours: int = 0) -> datetime:
        return self._context.start + timedelta(days=days, hours=hours)

    def _sector_id(self, slug: str) -> UUID:
        return self._derive("sector", slug)

    def _derive(self, kind: str, key: str) -> UUID:
        return uuid5(self._context.aqueduct_id, f"{ID_LABEL}:{kind}:{key}")
