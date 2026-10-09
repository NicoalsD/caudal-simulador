"""Export of confirmed shift executions for the minutes (actas), observed data only.

Confirmed executions are the shifts the operator recorded at the end of each day. The
export never includes ground truth (true level, demand, leaks) and states the period it
covers, so that an acta can cite the exact days.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from caudal_sim import __version__
from caudal_sim.export import FORMATS, Format, _sha256, _write
from caudal_sim.terrain import SimulationRun

ACTAS_FOLDER = "actas"
ACTAS_TABLE = "shift_executions_confirmed"
ACTAS_MANIFEST_NAME = "actas-manifest.json"
ACTAS_COLUMNS = [
    "day_index",
    "service_date",
    "sector_id",
    "start_hour",
    "end_hour",
    "outcome",
    "open_hours",
]
SOURCE_LABEL = "observed"


def export_confirmed_executions(
    run: SimulationRun, out_dir: Path, formats: tuple[Format, ...] = FORMATS
) -> Path:
    """Writes the confirmed shift executions and their manifest. Returns the manifest path."""
    frame = _confirmed_frame(run)
    folder = out_dir / ACTAS_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    written: dict[str, dict[str, Any]] = {}
    for fmt in formats:
        path = folder / f"{ACTAS_TABLE}.{fmt}"
        _write(frame, path, fmt)
        written[path.relative_to(out_dir).as_posix()] = {
            "rows": len(frame),
            "sha256": _sha256(path),
        }

    manifest = {
        "is_simulated": True,
        "source": SOURCE_LABEL,
        "truth_included": False,
        "scenario": run.scenario_name,
        "seed": run.seed,
        "simulator_version": __version__,
        "timezone": run.timezone,
        "period": _period(run),
        "formats": list(formats),
        "files": dict(sorted(written.items())),
    }
    manifest_path = out_dir / ACTAS_MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest_path


def _confirmed_frame(run: SimulationRun) -> pd.DataFrame:
    rows = [
        {
            **asdict(shift),
            "service_date": (run.start + timedelta(days=shift.day_index)).date().isoformat(),
            "outcome": shift.outcome.value,
        }
        for shift in run.observed.shift_executions
    ]
    return pd.DataFrame(rows, columns=ACTAS_COLUMNS)


def _period(run: SimulationRun) -> dict[str, str | int]:
    first = run.start.date()
    last = (run.start + timedelta(days=run.days - 1)).date()
    return {"start": first.isoformat(), "end": last.isoformat(), "days": run.days}
