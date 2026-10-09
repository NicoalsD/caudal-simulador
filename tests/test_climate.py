"""Pruebas del modelo de días húmedos y secos (cadena de Markov por mes)."""

from datetime import date

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from caudal_sim.climate import MonthlyMarkovClimate
from caudal_sim.scenario import MONTHS_PER_YEAR, MonthClimate

START = date(2026, 1, 1)
LONG_RUN_DAYS = 50_000
FEBRUARY = 2
JANUARY_DAYS = 31
FIRST_TWO_MONTHS_DAYS = 59
STATIONARY_TOLERANCE = 0.05
PROBABILITY_BOUNDS = st.floats(min_value=0.05, max_value=0.95)


RAIN_SHAPE = 0.8
RAIN_SCALE_MM = 6.0


def _row(month: int, p_after_dry: float, p_after_wet: float) -> MonthClimate:
    return MonthClimate(
        month=month,
        p_wet_after_dry=p_after_dry,
        p_wet_after_wet=p_after_wet,
        gamma_shape=RAIN_SHAPE,
        gamma_scale_mm=RAIN_SCALE_MM,
    )


def _constant_year(p_after_dry: float, p_after_wet: float) -> list[MonthClimate]:
    return [_row(month, p_after_dry, p_after_wet) for month in range(1, MONTHS_PER_YEAR + 1)]


def test_same_seed_gives_the_same_wet_days() -> None:
    model = MonthlyMarkovClimate(_constant_year(0.3, 0.6))

    first = model.wet_days(START, 365, np.random.default_rng(42))
    second = model.wet_days(START, 365, np.random.default_rng(42))

    np.testing.assert_array_equal(first, second)


def test_climate_that_never_rains_gives_no_wet_days() -> None:
    model = MonthlyMarkovClimate(_constant_year(0.0, 0.0))

    wet = model.wet_days(START, 365, np.random.default_rng(1))

    assert not wet.any()


def test_climate_with_certain_rain_is_wet_every_day() -> None:
    model = MonthlyMarkovClimate(_constant_year(1.0, 1.0))

    wet = model.wet_days(START, 365, np.random.default_rng(1))

    assert wet.all()


def test_probabilities_switch_with_the_calendar_month() -> None:
    # Enero nunca llueve; febrero siempre. Los días de enero no pueden ser húmedos.
    monthly = [
        _row(month, *((1.0, 1.0) if month == FEBRUARY else (0.0, 0.0)))
        for month in range(1, MONTHS_PER_YEAR + 1)
    ]
    model = MonthlyMarkovClimate(monthly)

    wet = model.wet_days(START, FIRST_TWO_MONTHS_DAYS, np.random.default_rng(7))
    january, february = wet[:JANUARY_DAYS], wet[JANUARY_DAYS:]

    assert not january.any()
    assert february.all()


@settings(max_examples=25)
@given(p_after_dry=PROBABILITY_BOUNDS, p_after_wet=PROBABILITY_BOUNDS)
def test_long_run_wet_fraction_approaches_the_stationary_value(
    p_after_dry: float, p_after_wet: float
) -> None:
    model = MonthlyMarkovClimate(_constant_year(p_after_dry, p_after_wet))

    wet = model.wet_days(START, LONG_RUN_DAYS, np.random.default_rng(2026))
    stationary = p_after_dry / (1.0 - p_after_wet + p_after_dry)

    assert abs(float(wet.mean()) - stationary) < STATIONARY_TOLERANCE


def test_negative_probabilities_are_rejected_by_the_scenario_model() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        _row(1, -0.1, 0.5)
