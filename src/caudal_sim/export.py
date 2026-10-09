"""Exportación de corridas a CSV y Parquet, con un manifiesto de hashes y de semilla."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from caudal_sim import __version__
from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.terrain import SimulationRun

Format = Literal["csv", "parquet"]
FORMATS: tuple[Format, ...] = ("csv", "parquet")
MANIFEST_NAME = "manifest.json"
HASH_CHUNK_BYTES = 1 << 20


def export_run(run: SimulationRun, out_dir: Path, formats: tuple[Format, ...] = FORMATS) -> Path:
    """Escribe observed/ y truth/ en los formatos pedidos y el manifiesto. Devuelve su ruta."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = _tables(run)
    written: dict[str, dict[str, Any]] = {}
    for folder, name, frame in tables:
        for fmt in formats:
            path = out_dir / folder / f"{name}.{fmt}"
            path.parent.mkdir(parents=True, exist_ok=True)
            _write(frame, path, fmt)
            relative = path.relative_to(out_dir).as_posix()
            written[relative] = {"rows": len(frame), "sha256": _sha256(path)}

    manifest = {
        "is_simulated": True,
        "scenario": run.scenario_name,
        "seed": run.seed,
        "days": run.days,
        "start": run.start.isoformat(),
        "timezone": run.timezone,
        "simulator_version": __version__,
        "formats": list(formats),
        "truth_is_never_sent_to_backend": True,
        "files": dict(sorted(written.items())),
    }
    manifest_path = out_dir / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest_path


def _tables(run: SimulationRun) -> list[tuple[str, str, pd.DataFrame]]:
    start = run.start
    truth = run.truth
    hours = np.arange(run.days * HOURS_PER_DAY)

    readings = pd.DataFrame(
        [asdict(item) for item in run.observed.readings],
        columns=[
            "reading_id",
            "observed_hour_index",
            "sent_hour_index",
            "gauge_m",
            "is_duplicate",
            "is_delayed",
        ],
    )
    readings.insert(
        2,
        "observed_at",
        [(start + timedelta(hours=int(h))).isoformat() for h in readings["observed_hour_index"]],
    )
    readings.insert(
        4,
        "sent_at",
        [(start + timedelta(hours=int(h))).isoformat() for h in readings["sent_hour_index"]],
    )

    shifts = pd.DataFrame(
        [{**asdict(item), "outcome": item.outcome.value} for item in run.observed.shift_executions],
        columns=[
            "day_index",
            "sector_id",
            "start_hour",
            "end_hour",
            "outcome",
            "open_hours",
        ],
    )
    damage = pd.DataFrame(
        [asdict(item) for item in run.observed.damage_reports],
        columns=["report_id", "day_index", "category"],
    )

    hourly = pd.DataFrame(
        {
            "hour_index": hours,
            "timestamp": [(start + timedelta(hours=int(h))).isoformat() for h in hours],
            "inflow_m3": truth.inflow_m3_per_hour,
            "muddy_water": truth.muddy_water,
            "requested_m3": truth.requested_m3_per_hour,
            "delivered_m3": truth.delivered_m3_per_hour,
            "overflow_m3": truth.overflow_m3_per_hour,
            "level_m": truth.level_m_per_hour,
            "leak_outflow_m3": truth.leak_outflow_m3_per_hour,
        }
    )
    rain = pd.DataFrame({"day_index": np.arange(run.days), "rain_mm": truth.daily_rain_mm})
    leaks = pd.DataFrame(
        [asdict(item) for item in truth.leaks],
        columns=[
            "leak_id",
            "start_day",
            "repair_day",
            "flow_m3_per_hour",
            "reported_day",
        ],
    )

    return [
        ("observed", "readings", readings),
        ("observed", "shift_executions", shifts),
        ("observed", "damage_reports", damage),
        ("truth", "hourly", hourly),
        ("truth", "daily_rain", rain),
        ("truth", "leaks", leaks),
    ]


def _write(frame: pd.DataFrame, path: Path, fmt: Format) -> None:
    if fmt == "csv":
        frame.to_csv(path, index=False, lineterminator="\n")
    else:
        frame.to_parquet(path, index=False, engine="pyarrow")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()
