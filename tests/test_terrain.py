"""Tests of the separation between observed data (backend) and ground truth."""

from dataclasses import fields
from pathlib import Path

import numpy as np

from caudal_sim.builder import load_scenario
from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.readings import TransmittedReading
from caudal_sim.shifts import ShiftExecution
from caudal_sim.terrain import DamageReport, ObservedData, TruthData, run_simulation

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal-year.yaml"
SIMULATED_DAYS = 30
SEED = 42
TRUTH_ONLY_WORDS = (
    "level",
    "volume",
    "leak",
    "overflow",
    "delivered",
    "requested",
    "rain",
    "muddy",
    "inflow",
    "demand",
    "true",
)
BALANCE_TOLERANCE_M3 = 1e-6


def _field_names(record: type) -> set[str]:
    return {item.name for item in fields(record)}


def test_observed_and_truth_have_no_shared_fields() -> None:
    assert not _field_names(ObservedData) & _field_names(TruthData)


def test_observed_records_carry_no_truth_columns() -> None:
    for record in (TransmittedReading, ShiftExecution, DamageReport):
        for name in _field_names(record):
            assert not any(word in name for word in TRUTH_ONLY_WORDS), f"{record.__name__}.{name}"


def test_observed_gauge_values_stay_inside_the_rule() -> None:
    scenario = load_scenario(NORMAL_YAML)

    run = run_simulation(scenario, SIMULATED_DAYS, SEED)

    gauges = [reading.gauge_m for reading in run.observed.readings]
    assert gauges
    assert all(scenario.tank.gauge_min <= value <= scenario.tank.gauge_max for value in gauges)


def test_truth_keeps_the_hourly_series_of_the_whole_run() -> None:
    scenario = load_scenario(NORMAL_YAML)

    run = run_simulation(scenario, SIMULATED_DAYS, SEED)
    hours = SIMULATED_DAYS * HOURS_PER_DAY

    assert run.truth.level_m_per_hour.shape == (hours,)
    assert run.truth.delivered_m3_per_hour.shape == (hours,)
    assert run.truth.daily_rain_mm.shape == (SIMULATED_DAYS,)


def test_whole_run_conserves_water() -> None:
    scenario = load_scenario(NORMAL_YAML)
    run = run_simulation(scenario, SIMULATED_DAYS, SEED)
    truth = run.truth
    area = scenario.tank.area_m2
    start_volume = area * scenario.tank.initial_gauge
    end_volume = area * float(truth.level_m_per_hour[-1])

    entered = float(truth.inflow_m3_per_hour.sum())
    left = float(truth.delivered_m3_per_hour.sum() + truth.overflow_m3_per_hour.sum())

    assert abs(entered - left - (end_volume - start_volume)) < BALANCE_TOLERANCE_M3
    assert np.all(truth.delivered_m3_per_hour <= truth.requested_m3_per_hour + BALANCE_TOLERANCE_M3)
