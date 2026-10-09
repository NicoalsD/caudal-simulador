"""Pruebas de las lecturas humanas: límites de la regla, redondeo, ruido y reproducibilidad."""

from pathlib import Path

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from caudal_sim.builder import load_scenario
from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.readings import GaussianRoundingReadingModel, take_readings
from caudal_sim.scenario import Scenario

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal.yaml"
SEED_MAX = 2**32 - 1
LEVEL_LOW_M = -1.0
LEVEL_HIGH_M = 7.0
FINE_STEP_M = 0.001
NOISE_SD_M = 0.02
SAMPLE_SIZE = 50_000
NOISE_TOLERANCE_RATIO = 0.1
GRID_TOLERANCE = 1e-6
SIMULATED_DAYS = 4
MID_LEVEL_M = 2.5


def _scenario() -> Scenario:
    return load_scenario(NORMAL_YAML)


@settings(max_examples=100)
@given(
    seed=st.integers(min_value=0, max_value=SEED_MAX),
    levels=st.lists(
        st.floats(min_value=LEVEL_LOW_M, max_value=LEVEL_HIGH_M, allow_nan=False),
        min_size=1,
        max_size=200,
    ),
)
def test_readings_stay_inside_the_gauge_and_on_its_grid(seed: int, levels: list[float]) -> None:
    scenario = _scenario()
    model = GaussianRoundingReadingModel(scenario.tank, scenario.readings.noise_sd_m)

    values = model.read(np.array(levels), np.random.default_rng(seed))

    tank = scenario.tank
    assert np.all(values >= tank.gauge_min)
    assert np.all(values <= tank.gauge_max)
    steps = (values - tank.gauge_min) / tank.gauge_step
    assert np.all(np.abs(steps - np.round(steps)) < GRID_TOLERANCE)


def test_zero_noise_gives_the_clipped_level_rounded_to_the_step() -> None:
    tank = _scenario().tank
    model = GaussianRoundingReadingModel(tank, noise_sd_m=0.0)
    levels = np.array([3.44, 3.46, 9.0, -2.0])

    values = model.read(levels, np.random.default_rng(0))

    np.testing.assert_allclose(values, [3.4, 3.5, tank.gauge_max, tank.gauge_min])


def test_reading_values_have_no_float_noise_in_decimals() -> None:
    tank = _scenario().tank
    model = GaussianRoundingReadingModel(tank, noise_sd_m=0.0)

    values = model.read(np.array([3.4]), np.random.default_rng(0))

    assert repr(float(values[0])) == "3.4"


def test_noise_spread_matches_the_configured_standard_deviation() -> None:
    tank = _scenario().tank.model_copy(update={"gauge_step": FINE_STEP_M})
    model = GaussianRoundingReadingModel(tank, noise_sd_m=NOISE_SD_M)
    levels = np.full(SAMPLE_SIZE, MID_LEVEL_M)

    values = model.read(levels, np.random.default_rng(12))
    spread = float(np.std(values - MID_LEVEL_M))

    assert abs(spread - NOISE_SD_M) / NOISE_SD_M < NOISE_TOLERANCE_RATIO


def test_take_readings_picks_the_configured_hours_of_each_day() -> None:
    scenario = _scenario()
    model = GaussianRoundingReadingModel(scenario.tank, 0.0)
    hourly_levels = np.arange(SIMULATED_DAYS * HOURS_PER_DAY, dtype=np.float64) % 5.0

    readings = take_readings(
        hourly_levels, SIMULATED_DAYS, scenario.readings.hours, model, np.random.default_rng(1)
    )

    assert len(readings) == SIMULATED_DAYS * len(scenario.readings.hours)
    assert [reading.reading_id for reading in readings] == list(range(len(readings)))
    assert {reading.hour for reading in readings} == set(scenario.readings.hours)
    first = readings[0]
    assert (first.day_index, first.hour) == (0, scenario.readings.hours[0])


def test_same_seed_gives_the_same_readings() -> None:
    scenario = _scenario()
    model = GaussianRoundingReadingModel(scenario.tank, scenario.readings.noise_sd_m)
    levels = np.linspace(0.0, 5.0, SIMULATED_DAYS * HOURS_PER_DAY)

    first = take_readings(
        levels, SIMULATED_DAYS, scenario.readings.hours, model, np.random.default_rng(8)
    )
    second = take_readings(
        levels, SIMULATED_DAYS, scenario.readings.hours, model, np.random.default_rng(8)
    )

    assert first == second
