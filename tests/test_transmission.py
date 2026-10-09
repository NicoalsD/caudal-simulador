"""Tests of duplicates and readings without signal: no reading is lost and each arrives in time."""

from pathlib import Path

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from caudal_sim.builder import load_scenario
from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.readings import (
    GaussianRoundingReadingModel,
    NoSignalDuplicateTransmission,
    Reading,
    take_readings,
)
from caudal_sim.scenario import ReadingSpec

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal.yaml"
SEED_MAX = 2**32 - 1
LONG_RUN_DAYS = 2000
RATE_TOLERANCE = 0.01
SIMULATED_DAYS = 10


def _readings(days: int) -> tuple[Reading, ...]:
    scenario = load_scenario(NORMAL_YAML)
    model = GaussianRoundingReadingModel(scenario.tank, scenario.readings.noise_sd_m)
    levels = np.full(days * HOURS_PER_DAY, 2.0)
    return take_readings(levels, days, scenario.readings.hours, model, np.random.default_rng(1))


def _spec(**overrides: float | int) -> ReadingSpec:
    values = load_scenario(NORMAL_YAML).readings.model_dump()
    values.update(overrides)
    return ReadingSpec.model_validate(values)


def test_without_faults_every_reading_arrives_when_observed() -> None:
    spec = _spec(duplicate_probability=0.0, no_signal_probability=0.0)
    readings = _readings(SIMULATED_DAYS)

    arrivals = NoSignalDuplicateTransmission(spec).transmit(readings, np.random.default_rng(3))

    assert len(arrivals) == len(readings)
    assert all(item.sent_hour_index == item.observed_hour_index for item in arrivals)
    assert not any(item.is_duplicate or item.is_delayed for item in arrivals)


@settings(max_examples=100)
@given(seed=st.integers(min_value=0, max_value=SEED_MAX))
def test_no_reading_is_lost_and_delays_stay_within_the_maximum(seed: int) -> None:
    spec = _spec(duplicate_probability=0.3, no_signal_probability=0.4, max_delay_hours=6)
    readings = _readings(SIMULATED_DAYS)

    arrivals = NoSignalDuplicateTransmission(spec).transmit(readings, np.random.default_rng(seed))

    assert {item.reading_id for item in arrivals} == {reading.reading_id for reading in readings}
    for item in arrivals:
        delay = item.sent_hour_index - item.observed_hour_index
        assert 0 <= delay <= spec.max_delay_hours
        if not item.is_delayed:
            assert delay == 0


def test_arrivals_are_in_time_order() -> None:
    spec = _spec(duplicate_probability=0.2, no_signal_probability=0.3)
    readings = _readings(SIMULATED_DAYS)

    arrivals = NoSignalDuplicateTransmission(spec).transmit(readings, np.random.default_rng(5))

    sent = [item.sent_hour_index for item in arrivals]
    assert sent == sorted(sent)


def test_long_run_rates_approach_the_configured_probabilities() -> None:
    spec = _spec(duplicate_probability=0.1, no_signal_probability=0.2)
    readings = _readings(LONG_RUN_DAYS)

    arrivals = NoSignalDuplicateTransmission(spec).transmit(readings, np.random.default_rng(2026))
    duplicate_rate = sum(item.is_duplicate for item in arrivals) / len(readings)
    delayed_rate = sum(item.is_delayed for item in arrivals) / len(readings)

    assert abs(duplicate_rate - spec.duplicate_probability) < RATE_TOLERANCE
    assert abs(delayed_rate - spec.no_signal_probability) < RATE_TOLERANCE


def test_same_seed_gives_the_same_arrivals() -> None:
    spec = _spec(duplicate_probability=0.2, no_signal_probability=0.3)
    readings = _readings(SIMULATED_DAYS)
    model = NoSignalDuplicateTransmission(spec)

    first = model.transmit(readings, np.random.default_rng(7))
    second = model.transmit(readings, np.random.default_rng(7))

    assert first == second
