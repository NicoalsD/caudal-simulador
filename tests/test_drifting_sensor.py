"""Decorator that adds a gradual drift to a sensor, and composition of the sensor decorators."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from caudal_sim.sensors import DriftingSensor, NoisySensor, SourceSensor, StuckSensor

DRIFT_START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
TRUE_LEVEL_M = 3.40
DRIFT_M_PER_DAY = 0.02
TWO_DAYS = timedelta(days=2)
HALF_DAY = timedelta(hours=12)
BEFORE_START = DRIFT_START - timedelta(hours=6)
STUCK_FROM = DRIFT_START + timedelta(days=1)
STUCK_UNTIL = DRIFT_START + timedelta(days=3)
SEED = 42
ABS_TOLERANCE = 1e-9


def _source() -> SourceSensor:
    return SourceSensor(lambda _at: TRUE_LEVEL_M)


def test_no_drift_before_the_start() -> None:
    sensor = DriftingSensor(_source(), DRIFT_M_PER_DAY, DRIFT_START)

    assert sensor.read(BEFORE_START) == TRUE_LEVEL_M


def test_drift_grows_linearly_with_the_days_since_the_start() -> None:
    sensor = DriftingSensor(_source(), DRIFT_M_PER_DAY, DRIFT_START)

    assert sensor.read(DRIFT_START + HALF_DAY) == pytest.approx(
        TRUE_LEVEL_M + DRIFT_M_PER_DAY / 2, abs=ABS_TOLERANCE
    )
    assert sensor.read(DRIFT_START + TWO_DAYS) == pytest.approx(
        TRUE_LEVEL_M + 2 * DRIFT_M_PER_DAY, abs=ABS_TOLERANCE
    )


def test_zero_drift_is_transparent() -> None:
    sensor = DriftingSensor(_source(), 0.0, DRIFT_START)

    assert sensor.read(DRIFT_START + TWO_DAYS) == TRUE_LEVEL_M


def test_drift_applied_over_noise_stays_a_linear_offset() -> None:
    noisy_seed = 7
    plain = NoisySensor(_source(), np.random.default_rng(noisy_seed), 0.0)
    drifting = DriftingSensor(
        NoisySensor(_source(), np.random.default_rng(noisy_seed), 0.0),
        DRIFT_M_PER_DAY,
        DRIFT_START,
    )
    at = DRIFT_START + TWO_DAYS

    assert drifting.read(at) - plain.read(at) == pytest.approx(
        2 * DRIFT_M_PER_DAY, abs=ABS_TOLERANCE
    )


def test_decorators_compose_in_any_order_with_different_results() -> None:
    at_stuck = STUCK_FROM + HALF_DAY
    at_later = at_stuck + HALF_DAY
    # Drift outside the stuck decorator: the frozen value is the inner one, and the drift
    # keeps growing on top of it.
    drift_over_stuck = DriftingSensor(
        StuckSensor(_source(), STUCK_FROM, STUCK_UNTIL), DRIFT_M_PER_DAY, DRIFT_START
    )
    # Drift inside the stuck decorator: the frozen value already carries the drift.
    stuck_over_drift = StuckSensor(
        DriftingSensor(_source(), DRIFT_M_PER_DAY, DRIFT_START), STUCK_FROM, STUCK_UNTIL
    )

    first_read = drift_over_stuck.read(at_stuck)
    later_read = drift_over_stuck.read(at_later)
    frozen_read = stuck_over_drift.read(at_stuck)
    frozen_later = stuck_over_drift.read(at_later)

    assert later_read - first_read == pytest.approx(DRIFT_M_PER_DAY * 0.5, abs=ABS_TOLERANCE)
    assert frozen_read == pytest.approx(first_read, abs=ABS_TOLERANCE)
    assert frozen_later == pytest.approx(frozen_read, abs=ABS_TOLERANCE)
