"""Historical backfill: turns a simulated run into import batches and sends them to the API.

Each batch respects the contract limits (5.000 rows and 1 MiB per request). Every batch
carries `file_sha256`, the SHA-256 of its own canonical rows, so a repeated batch is
recognised by the backend. Dry runs build and count the batches and send nothing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from caudal_sim import __version__
from caudal_sim.api_client import (
    UNEXPECTED_ERROR_CODE,
    UNEXPECTED_ERROR_MESSAGE,
    UNKNOWN_STATUS,
    ApiError,
    CaudalApiClient,
    encode_json,
)
from caudal_sim.api_payload import ApiPayloadAdapter, ImportContext, ImportPayloadTarget
from caudal_sim.config import SimulatorSettings
from caudal_sim.demo_guard import DemoTargetGuard
from caudal_sim.scenario import Scenario
from caudal_sim.terrain import SimulationRun

MAX_IMPORT_ROWS = 5000
MAX_IMPORT_BODY_BYTES = 1 << 20
ROW_SEPARATOR_BYTES = 1
SHA256_HEX_LENGTH = 64
PLACEHOLDER_SHA256 = "0" * SHA256_HEX_LENGTH
ROWS_KEY = "rows"
ROWS_ACCEPTED_KEY = "rows_accepted"
ROWS_REJECTED_KEY = "rows_rejected"


class ImportKind(StrEnum):
    """Kinds of history the API imports, named as the CLI subcommands."""

    READINGS = "readings"


IMPORT_PATHS: dict[ImportKind, str] = {
    ImportKind.READINGS: "/api/v1/imports/readings",
}


class ImportLimitError(ValueError):
    """A single row does not fit in one request, so the batch cannot be built."""


@dataclass(frozen=True)
class ImportBatch:
    """One request body for an import endpoint, with the number of rows it carries."""

    path: str
    body: Mapping[str, Any]
    row_count: int
    file_sha256: str


@dataclass(frozen=True)
class BatchMetadata:
    """Fields shared by all batches of one run, as the import contract defines them."""

    aqueduct_id: UUID
    scenario_name: str
    seed: int


@dataclass(frozen=True)
class BackfillSummary:
    """What a backfill did, or would do in a dry run."""

    kind: ImportKind
    rows_total: int
    duplicates_skipped: int
    batches: int
    rows_accepted: int
    rows_rejected: int
    dry_run: bool


def build_batches(
    path: str, rows: Sequence[Mapping[str, Any]], metadata: BatchMetadata
) -> tuple[ImportBatch, ...]:
    """Splits rows into request bodies that stay within the row and byte limits."""
    base_body = _body(metadata, [], PLACEHOLDER_SHA256)
    base_bytes = len(encode_json(base_body))
    batches: list[ImportBatch] = []
    chunk: list[Mapping[str, Any]] = []
    chunk_bytes = base_bytes
    for row in rows:
        row_bytes = len(encode_json(row)) + ROW_SEPARATOR_BYTES
        if base_bytes + row_bytes > MAX_IMPORT_BODY_BYTES:
            raise ImportLimitError("Una fila supera el tamaño máximo de un lote.")
        is_full = len(chunk) == MAX_IMPORT_ROWS or chunk_bytes + row_bytes > MAX_IMPORT_BODY_BYTES
        if chunk and is_full:
            batches.append(_make_batch(path, metadata, chunk))
            chunk = []
            chunk_bytes = base_bytes
        chunk.append(row)
        chunk_bytes += row_bytes
    if chunk:
        batches.append(_make_batch(path, metadata, chunk))
    return tuple(batches)


def rows_for(
    kind: ImportKind, run: SimulationRun, adapter: ImportPayloadTarget
) -> list[dict[str, Any]]:
    """Converts the observed records of one kind into import rows."""
    if kind is ImportKind.READINGS:
        return [
            adapter.reading_row(reading)
            for reading in run.observed.readings
            if not reading.is_duplicate
        ]
    raise ValueError(f"Tipo de importación no soportado: {kind}")


def run_backfill(
    kind: ImportKind,
    scenario: Scenario,
    run: SimulationRun,
    settings: SimulatorSettings,
    *,
    dry_run: bool,
) -> BackfillSummary:
    """Builds the batches for `kind` and, unless `dry_run`, checks the demo target and sends them.

    The dry run never contacts the API, so it does not check the demo target or log in.
    """
    context = ImportContext(
        aqueduct_id=settings.aqueduct_id,
        tank_id=settings.tank_id,
        start=run.start,
        sector_slugs=tuple(sector.id for sector in scenario.sectors),
    )
    adapter = ApiPayloadAdapter(context)
    rows = rows_for(kind, run, adapter)
    duplicates = _duplicate_count(run)
    path = IMPORT_PATHS[kind]
    metadata = BatchMetadata(
        aqueduct_id=settings.aqueduct_id, scenario_name=run.scenario_name, seed=run.seed
    )
    batches = build_batches(path, rows, metadata)

    accepted = 0
    rejected = 0
    if not dry_run:
        accepted, rejected = _send(batches, settings)
    return BackfillSummary(
        kind=kind,
        rows_total=len(rows),
        duplicates_skipped=duplicates,
        batches=len(batches),
        rows_accepted=accepted,
        rows_rejected=rejected,
        dry_run=dry_run,
    )


def _send(batches: Sequence[ImportBatch], settings: SimulatorSettings) -> tuple[int, int]:
    accepted = 0
    rejected = 0
    with CaudalApiClient(
        settings.api_base_url, timeout_seconds=settings.http_timeout_seconds
    ) as client:
        DemoTargetGuard(client, settings.demo_aqueduct_slug).ensure_demo()
        client.login(settings.api_username, settings.api_password)
        for batch in batches:
            response = client.post_import(batch.path, batch.body)
            accepted += _count(response, ROWS_ACCEPTED_KEY)
            rejected += _count(response, ROWS_REJECTED_KEY)
    return accepted, rejected


def _count(response: Mapping[str, Any], key: str) -> int:
    value = response.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiError(UNKNOWN_STATUS, UNEXPECTED_ERROR_CODE, UNEXPECTED_ERROR_MESSAGE)
    return value


def _duplicate_count(run: SimulationRun) -> int:
    return sum(1 for reading in run.observed.readings if reading.is_duplicate)


def _make_batch(
    path: str, metadata: BatchMetadata, rows: Sequence[Mapping[str, Any]]
) -> ImportBatch:
    file_sha256 = hashlib.sha256(encode_json({ROWS_KEY: list(rows)})).hexdigest()
    return ImportBatch(
        path=path,
        body=_body(metadata, list(rows), file_sha256),
        row_count=len(rows),
        file_sha256=file_sha256,
    )


def _body(
    metadata: BatchMetadata,
    rows: list[Mapping[str, Any]],
    file_sha256: str,
) -> dict[str, Any]:
    return {
        "aqueduct_id": str(metadata.aqueduct_id),
        "scenario_name": metadata.scenario_name,
        "seed": metadata.seed,
        "simulator_version": __version__,
        "file_sha256": file_sha256,
        ROWS_KEY: rows,
    }
