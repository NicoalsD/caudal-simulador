"""Pruebas de la cantidad de lluvia (gamma por mes) y de su reproducibilidad."""

from datetime import date

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from caudal_sim.climate import GammaRainfall
from caudal_sim.scenario import MONTHS_PER_YEAR, MonthClimate

START = date(2026, 1, 1)
YEAR_DAYS = 365
SAMPLE_DAYS = 200_000
MEAN_TOLERANCE_RATIO = 0.05
CONSTANT_SHAPE = 0.8
CONSTANT_SCALE = 6.0


def _constant_year(shape: float, scale: float) -> list[MonthClimate]:
    return [
        MonthClimate(
            month=month,
            p_wet_after_dry=0.5,
            p_wet_after_wet=0.5,
            gamma_shape=shape,
            gamma_scale_mm=scale,
        )
        for month in range(1, MONTHS_PER_YEAR + 1)
    ]


def test_dry_days_have_no_rain() -> None:
    model = GammaRainfall(_constant_year(CONSTANT_SHAPE, CONSTANT_SCALE))
    wet = np.zeros(YEAR_DAYS, dtype=np.bool_)

    amounts = model.amounts_mm(wet, START, np.random.default_rng(3))

    assert np.all(amounts == 0.0)


def test_wet_days_have_positive_rain() -> None:
    model = GammaRainfall(_constant_year(CONSTANT_SHAPE, CONSTANT_SCALE))
    wet = np.ones(YEAR_DAYS, dtype=np.bool_)

    amounts = model.amounts_mm(wet, START, np.random.default_rng(3))

    assert np.all(amounts > 0.0)


def test_mean_wet_day_rain_matches_gamma_mean() -> None:
    model = GammaRainfall(_constant_year(CONSTANT_SHAPE, CONSTANT_SCALE))
    wet = np.ones(SAMPLE_DAYS, dtype=np.bool_)

    amounts = model.amounts_mm(wet, START, np.random.default_rng(11))
    expected_mean = CONSTANT_SHAPE * CONSTANT_SCALE

    assert abs(float(amounts.mean()) - expected_mean) / expected_mean < MEAN_TOLERANCE_RATIO


@settings(max_examples=40)
@given(seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_same_seed_gives_the_same_rain_for_any_wet_pattern(seed: int) -> None:
    model = GammaRainfall(_constant_year(CONSTANT_SHAPE, CONSTANT_SCALE))
    every_day = np.ones(YEAR_DAYS, dtype=np.bool_)
    every_other_day = np.arange(YEAR_DAYS) % 2 == 0

    full = model.amounts_mm(every_day, START, np.random.default_rng(seed))
    partial = model.amounts_mm(every_other_day, START, np.random.default_rng(seed))

    np.testing.assert_array_equal(partial[every_other_day], full[every_other_day])
    assert np.all(partial[~every_other_day] == 0.0)
