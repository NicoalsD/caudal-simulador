"""Decorator that freezes the reading of a sensor inside a window (P09)."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from caudal_sim.sensors import SourceSensor, StuckSensor
from caudal_sim.simulation_step import SimulationStep
from caudal_sim.snapshot import SimulationRun

START = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
STUCK_FROM = START + timedelta(minutes=10)
STUCK_UNTIL = START + timedelta(minutes=20)
BEFORE = START + timedelta(minutes=5)
INSIDE = START + timedelta(minutes=12)
LATER_INSIDE = START + timedelta(minutes=15)
AFTER = START + timedelta(minutes=25)
ONE_MINUTE = timedelta(minutes=1)
LEVEL_AT_WINDOW_START_M = 3.40
LEVEL_LATER_M = 3.55
SEED = 0


class Level:
    """A tank level that a test can change while the sensor runs."""

    def __init__(self, value: float) -> None:
        self.value = value


def test_readings_before_the_window_follow_the_inner_sensor() -> None:
    level = Level(LEVEL_AT_WINDOW_START_M)
    sensor = StuckSensor(SourceSensor(lambda _at: level.value), STUCK_FROM, STUCK_UNTIL)

    assert sensor.read(BEFORE) == LEVEL_AT_WINDOW_START_M


def test_reading_inside_the_window_keeps_the_first_value() -> None:
    level = Level(LEVEL_AT_WINDOW_START_M)
    sensor = StuckSensor(SourceSensor(lambda _at: level.value), STUCK_FROM, STUCK_UNTIL)

    first = sensor.read(INSIDE)
    level.value = LEVEL_LATER_M
    second = sensor.read(LATER_INSIDE)

    assert first == second == LEVEL_AT_WINDOW_START_M


def test_after_the_window_the_inner_sensor_is_back() -> None:
    level = Level(LEVEL_AT_WINDOW_START_M)
    sensor = StuckSensor(SourceSensor(lambda _at: level.value), STUCK_FROM, STUCK_UNTIL)
    sensor.read(INSIDE)
    level.value = LEVEL_LATER_M

    assert sensor.read(AFTER) == LEVEL_LATER_M


def test_window_must_end_after_it_starts() -> None:
    source = SourceSensor(lambda _at: LEVEL_LATER_M)

    with pytest.raises(ValueError, match="después de empezar"):
        StuckSensor(source, STUCK_UNTIL, STUCK_FROM)


def test_snapshot_taken_inside_the_window_restores_the_frozen_value() -> None:
    level = Level(LEVEL_AT_WINDOW_START_M)
    sensor = StuckSensor(SourceSensor(lambda _at: level.value), STUCK_FROM, STUCK_UNTIL)

    class ReadStep(SimulationStep):
        def _advance(self, now: datetime, elapsed: timedelta) -> None:
            sensor.read(now)

    run = SimulationRun(
        INSIDE, np.random.default_rng(SEED), steps=[ReadStep()], components=[sensor]
    )
    run.advance(ONE_MINUTE)
    snapshot = run.create_snapshot()
    level.value = LEVEL_LATER_M
    run.advance(ONE_MINUTE)

    run.restore(snapshot)

    assert sensor.read(LATER_INSIDE) == LEVEL_AT_WINDOW_START_M
