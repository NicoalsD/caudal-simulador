"""Historical backfill: turns a simulated run into import batches and sends them to the API.

Each batch respects the contract limits (5.000 rows and 1 MiB per request). Every batch
carries `file_sha256`, the SHA-256 of its own canonical rows, so a repeated batch is
recognised by the backend. Dry runs build and count the batches and send nothing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

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
from caudal_sim.signing import (
    SIGNATURE_SUFFIX,
    load_private_key,
    public_key_fingerprint,
    sign_bytes,
)
from caudal_sim.terrain import SimulationRun

MAX_IMPORT_ROWS = 5000
MAX_IMPORT_BODY_BYTES = 1 << 20
ROW_SEPARATOR_BYTES = 1
SHA256_HEX_LENGTH = 64
PLACEHOLDER_SHA256 = "0" * SHA256_HEX_LENGTH
ROWS_KEY = "rows"
ROWS_ACCEPTED_KEY = "rows_accepted"
ROWS_REJECTED_KEY = "rows_rejected"
DEFAULT_MANIFEST_DIR = Path("outputs") / "imports"
MANIFEST_SUFFIX = "-manifest.json"
MANIFEST_INDENT = 2


class ImportKind(StrEnum):
    """Kinds of history the API imports, named as the CLI subcommands."""

    READINGS = "readings"
    SHIFT_EXECUTIONS = "shift-executions"
    INCIDENTS = "incidents"


IMPORT_PATHS: dict[ImportKind, str] = {
    ImportKind.READINGS: "/api/v1/imports/readings",
    ImportKind.SHIFT_EXECUTIONS: "/api/v1/imports/shift-executions",
    ImportKind.INCIDENTS: "/api/v1/imports/incidents",
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
class BackfillOptions:
    """How a backfill runs: a dry run only counts; a real run signs and sends."""

    dry_run: bool = False
    manifest_dir: Path = DEFAULT_MANIFEST_DIR


@dataclass(frozen=True)
class ImportPlan:
    """Everything a manifest records about one backfill, before anything is sent."""

    kind: ImportKind
    metadata: BatchMetadata
    batches: tuple[ImportBatch, ...]
    rows_total: int
    duplicates_skipped: int


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
    manifest_path: Path | None


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
    if kind is ImportKind.SHIFT_EXECUTIONS:
        return [adapter.shift_execution_row(shift) for shift in run.observed.shift_executions]
    if kind is ImportKind.INCIDENTS:
        return [adapter.incident_row(report) for report in run.observed.damage_reports]
    raise ValueError(f"Tipo de importación no soportado: {kind}")


def run_backfill(
    kind: ImportKind,
    scenario: Scenario,
    run: SimulationRun,
    settings: SimulatorSettings,
    options: BackfillOptions | None = None,
) -> BackfillSummary:
    """Builds the batches for `kind` and, unless `dry_run`, signs a manifest and sends them.

    The dry run never contacts the API, never reads the signing key and writes nothing. A real
    run checks the demo target first and signs the manifest before logging in.
    """
    context = ImportContext(
        aqueduct_id=settings.aqueduct_id,
        tank_id=settings.tank_id,
        start=run.start,
        sector_slugs=tuple(sector.id for sector in scenario.sectors),
    )
    adapter = ApiPayloadAdapter(context)
    rows = rows_for(kind, run, adapter)
    duplicates = _duplicate_count(kind, run)
    path = IMPORT_PATHS[kind]
    metadata = BatchMetadata(
        aqueduct_id=settings.aqueduct_id, scenario_name=run.scenario_name, seed=run.seed
    )
    batches = build_batches(path, rows, metadata)

    options = options or BackfillOptions()
    plan = ImportPlan(
        kind=kind,
        metadata=metadata,
        batches=batches,
        rows_total=len(rows),
        duplicates_skipped=duplicates,
    )
    if options.dry_run:
        return BackfillSummary(
            kind=kind,
            rows_total=plan.rows_total,
            duplicates_skipped=duplicates,
            batches=len(batches),
            rows_accepted=0,
            rows_rejected=0,
            dry_run=True,
            manifest_path=None,
        )
    accepted, rejected, manifest_path = _send(plan, settings, options.manifest_dir)
    return BackfillSummary(
        kind=kind,
        rows_total=plan.rows_total,
        duplicates_skipped=duplicates,
        batches=len(batches),
        rows_accepted=accepted,
        rows_rejected=rejected,
        dry_run=False,
        manifest_path=manifest_path,
    )


def _write_signed_manifest(plan: ImportPlan, manifest_dir: Path, key: Ed25519PrivateKey) -> Path:
    """Writes the manifest of the batches and its Ed25519 signature next to it.

    The manifest holds hashes and counts only. The private key never enters the file.
    """
    metadata = plan.metadata
    manifest: dict[str, Any] = {
        "is_simulated": True,
        "kind": plan.kind.value,
        "aqueduct_id": str(metadata.aqueduct_id),
        "scenario_name": metadata.scenario_name,
        "seed": metadata.seed,
        "simulator_version": __version__,
        "rows_total": plan.rows_total,
        "duplicates_skipped": plan.duplicates_skipped,
        "signing_key_fingerprint": public_key_fingerprint(key),
        "batches": [
            {"path": batch.path, "row_count": batch.row_count, "file_sha256": batch.file_sha256}
            for batch in plan.batches
        ],
    }
    data = (
        json.dumps(manifest, indent=MANIFEST_INDENT, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{plan.kind.value}{MANIFEST_SUFFIX}"
    manifest_path.write_bytes(data)
    signature_path = manifest_path.with_name(manifest_path.name + SIGNATURE_SUFFIX)
    signature_path.write_text(sign_bytes(data, key) + "\n", encoding="ascii")
    return manifest_path


def _send(
    plan: ImportPlan, settings: SimulatorSettings, manifest_dir: Path
) -> tuple[int, int, Path]:
    """Checks the demo target, signs the manifest, then logs in and sends every batch.

    The order matters: nothing is signed or sent for a target that is not the demo aqueduct.
    """
    accepted = 0
    rejected = 0
    with CaudalApiClient(
        settings.api_base_url, timeout_seconds=settings.http_timeout_seconds
    ) as client:
        DemoTargetGuard(client, settings.demo_aqueduct_slug).ensure_demo()
        key = load_private_key(settings.private_key_path)
        manifest_path = _write_signed_manifest(plan, manifest_dir, key)
        client.login(settings.api_username, settings.api_password)
        for batch in plan.batches:
            response = client.post_import(batch.path, batch.body)
            accepted += _count(response, ROWS_ACCEPTED_KEY)
            rejected += _count(response, ROWS_REJECTED_KEY)
    return accepted, rejected, manifest_path


def _count(response: Mapping[str, Any], key: str) -> int:
    value = response.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiError(UNKNOWN_STATUS, UNEXPECTED_ERROR_CODE, UNEXPECTED_ERROR_MESSAGE)
    return value


def _duplicate_count(kind: ImportKind, run: SimulationRun) -> int:
    if kind is ImportKind.READINGS:
        return sum(1 for reading in run.observed.readings if reading.is_duplicate)
    return 0


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
