"""Historical windows for the AI backtest, written as two separate datasets.

Each window is a span of `WINDOW_DAYS` days of observed readings (the model input) followed
by `HORIZON_DAYS` days of true level (the target the forecast is scored against). The two
datasets live in different folders with their own manifests, so the observed inputs never
carry ground truth and the targets never reach the forecast as input.

@pattern P20 Template Method
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, final

import pandas as pd

from caudal_sim import __version__
from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.export import FORMATS, Format, _sha256, _write
from caudal_sim.terrain import SimulationRun

BACKTEST_FOLDER = "backtest"
INPUTS_FOLDER = "observed-inputs"
TARGETS_FOLDER = "truth-targets"
BACKTEST_MANIFEST_NAME = "backtest-manifest.json"
WINDOW_DAYS = 7
HORIZON_DAYS = 1
STRIDE_DAYS = 1
INPUT_HOURS = WINDOW_DAYS * HOURS_PER_DAY
HORIZON_HOURS = HORIZON_DAYS * HOURS_PER_DAY


@dataclass(frozen=True)
class WindowSpec:
    """One backtest window, in simulation hours: input span and target span."""

    window_id: int
    input_start_hour: int
    horizon_start_hour: int

    @property
    def input_end_hour(self) -> int:
        """First hour after the input span (exclusive)."""
        return self.input_start_hour + INPUT_HOURS

    @property
    def horizon_end_hour(self) -> int:
        """First hour after the target span (exclusive)."""
        return self.horizon_start_hour + HORIZON_HOURS


def windows_for(days: int) -> tuple[WindowSpec, ...]:
    """Sliding windows that fit entirely inside the simulated days."""
    total_hours = days * HOURS_PER_DAY
    windows: list[WindowSpec] = []
    start_hour = 0
    while start_hour + INPUT_HOURS + HORIZON_HOURS <= total_hours:
        windows.append(
            WindowSpec(
                window_id=len(windows),
                input_start_hour=start_hour,
                horizon_start_hour=start_hour + INPUT_HOURS,
            )
        )
        start_hour += STRIDE_DAYS * HOURS_PER_DAY
    return tuple(windows)


class BacktestExporter(ABC):
    """Template for one backtest dataset.

    `export` is the template method: it fixes the order of the steps (build the table, write
    the files, write the manifest). Subclasses only decide what the table contains and where
    it goes; they cannot change the order.

    @pattern P20 Template Method
    """

    folder: str
    source_label: str
    truth_included: bool

    @final
    def export(
        self, run: SimulationRun, out_dir: Path, formats: tuple[Format, ...] = FORMATS
    ) -> Path:
        """Writes the dataset and its manifest. Returns the manifest path."""
        windows = windows_for(run.days)
        table = self.build_table(run, windows)
        target = out_dir / BACKTEST_FOLDER / self.folder
        written = self._write_files(table, target, formats, out_dir)
        return self._write_manifest(run, windows, target, formats, written)

    @abstractmethod
    def build_table(self, run: SimulationRun, windows: tuple[WindowSpec, ...]) -> pd.DataFrame:
        """Hook: the rows of this dataset, one per window and hour."""

    def _write_files(
        self, table: pd.DataFrame, target: Path, formats: tuple[Format, ...], out_dir: Path
    ) -> dict[str, dict[str, Any]]:
        target.mkdir(parents=True, exist_ok=True)
        written: dict[str, dict[str, Any]] = {}
        for fmt in formats:
            path = target / f"windows.{fmt}"
            _write(table, path, fmt)
            written[path.relative_to(out_dir).as_posix()] = {
                "rows": len(table),
                "sha256": _sha256(path),
            }
        return written

    def _write_manifest(
        self,
        run: SimulationRun,
        windows: tuple[WindowSpec, ...],
        target: Path,
        formats: tuple[Format, ...],
        written: dict[str, dict[str, Any]],
    ) -> Path:
        manifest = {
            "is_simulated": True,
            "dataset": self.folder,
            "source": self.source_label,
            "truth_included": self.truth_included,
            "scenario": run.scenario_name,
            "seed": run.seed,
            "simulator_version": __version__,
            "timezone": run.timezone,
            "start": run.start.isoformat(),
            "days": run.days,
            "window_days": WINDOW_DAYS,
            "horizon_days": HORIZON_DAYS,
            "stride_days": STRIDE_DAYS,
            "window_count": len(windows),
            "formats": list(formats),
            "files": dict(sorted(written.items())),
        }
        manifest_path = target / BACKTEST_MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return manifest_path


class ObservedInputsExporter(BacktestExporter):
    """Observed readings inside each input span. Duplicates are skipped."""

    folder = INPUTS_FOLDER
    source_label = "observed"
    truth_included = False

    def build_table(self, run: SimulationRun, windows: tuple[WindowSpec, ...]) -> pd.DataFrame:
        rows = [
            {
                "window_id": window.window_id,
                "hour_offset": reading.observed_hour_index - window.input_start_hour,
                "gauge_m": reading.gauge_m,
                "is_delayed": reading.is_delayed,
            }
            for window in windows
            for reading in run.observed.readings
            if not reading.is_duplicate
            and window.input_start_hour <= reading.observed_hour_index < window.input_end_hour
        ]
        return pd.DataFrame(rows, columns=["window_id", "hour_offset", "gauge_m", "is_delayed"])


class TruthTargetsExporter(BacktestExporter):
    """True level in each target span. Never used as model input."""

    folder = TARGETS_FOLDER
    source_label = "truth"
    truth_included = True

    def build_table(self, run: SimulationRun, windows: tuple[WindowSpec, ...]) -> pd.DataFrame:
        rows = [
            {
                "window_id": window.window_id,
                "hour_offset": hour - window.horizon_start_hour,
                "level_m": float(run.truth.level_m_per_hour[hour]),
            }
            for window in windows
            for hour in range(window.horizon_start_hour, window.horizon_end_hour)
        ]
        return pd.DataFrame(rows, columns=["window_id", "hour_offset", "level_m"])


def export_backtest_windows(
    run: SimulationRun, out_dir: Path, formats: tuple[Format, ...] = FORMATS
) -> tuple[Path, Path]:
    """Writes the observed inputs and the truth targets. Returns both manifest paths."""
    inputs = ObservedInputsExporter().export(run, out_dir, formats)
    targets = TruthTargetsExporter().export(run, out_dir, formats)
    return inputs, targets
