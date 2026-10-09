"""Decorator that adds reading noise to a sensor (P09)."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from caudal_sim.sensors import NoisySensor, SourceSensor
from caudal_sim.simulation_step import SimulationStep
from caudal_sim.snapshot import SimulationRun

AT = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
TRUE_LEVEL_M = 3.4
SIGMA_M = 0.02
SAMPLES = 2000
SEED = 42
MEAN_TOLERANCE_M = 0.01
ONE_MINUTE = timedelta(minutes=1)


def _source() -> SourceSensor:
    return SourceSensor(lambda _at: TRUE_LEVEL_M)


def test_zero_noise_returns_the_inner_reading_unchanged() -> None:
    sensor = NoisySensor(_source(), np.random.default_rng(SEED), 0.0)

    assert sensor.read(AT) == TRUE_LEVEL_M


def test_same_seed_gives_the_same_readings() -> None:
    first = NoisySensor(_source(), np.random.default_rng(SEED), SIGMA_M)
    second = NoisySensor(_source(), np.random.default_rng(SEED), SIGMA_M)

    assert [first.read(AT) for _ in range(5)] == [second.read(AT) for _ in range(5)]


def test_readings_scatter_around_the_true_level() -> None:
    sensor = NoisySensor(_source(), np.random.default_rng(SEED), SIGMA_M)

    readings = [sensor.read(AT) for _ in range(SAMPLES)]

    assert np.mean(readings) == pytest.approx(TRUE_LEVEL_M, abs=MEAN_TOLERANCE_M)
    assert np.std(readings) == pytest.approx(SIGMA_M, rel=0.1)


def test_negative_noise_is_rejected() -> None:
    with pytest.raises(ValueError, match="no puede ser negativa"):
        NoisySensor(_source(), np.random.default_rng(SEED), -SIGMA_M)


def test_decorators_compose_with_each_other() -> None:
    inner = NoisySensor(_source(), np.random.default_rng(SEED), 0.0)
    outer = NoisySensor(inner, np.random.default_rng(SEED), 0.0)

    assert outer.read(AT) == TRUE_LEVEL_M


def test_restoring_a_run_repeats_the_noisy_readings() -> None:
    rng = np.random.default_rng(SEED)
    sensor = NoisySensor(_source(), rng, SIGMA_M)
    readings: list[float] = []

    class ReadStep(SimulationStep):
        def _advance(self, now: datetime, elapsed: timedelta) -> None:
            readings.append(sensor.read(now))

    run = SimulationRun(AT, rng, steps=[ReadStep()], components=[])
    run.advance(ONE_MINUTE)
    snapshot = run.create_snapshot()
    run.advance(ONE_MINUTE)
    after_first_pass = readings[1]

    run.restore(snapshot)
    run.advance(ONE_MINUTE)

    assert readings[2] == after_first_pass
