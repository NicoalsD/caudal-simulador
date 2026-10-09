"""Pruebas del caudal de la fuente: base, retardo de la lluvia y agua con barro."""

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.scenario import SourceSpec
from caudal_sim.source import LaggedRainSource

BASE_FLOW = 1.2
GAIN = 0.15
LAG_HOURS = 36.0
THRESHOLD_MM = 20.0
MUDDY_HOURS = 48
DAYS = 30
RAIN_DAY = 5


def _spec(**overrides: float | int) -> SourceSpec:
    values: dict[str, float | int] = {
        "base_flow_m3_per_hour": BASE_FLOW,
        "rain_gain_m3_per_hour_per_mm": GAIN,
        "response_lag_hours": LAG_HOURS,
        "muddy_rain_threshold_mm": THRESHOLD_MM,
        "muddy_duration_hours": MUDDY_HOURS,
    }
    values.update(overrides)
    return SourceSpec.model_validate(values)


def _single_storm(mm: float) -> np.ndarray:
    rain = np.zeros(DAYS, dtype=np.float64)
    rain[RAIN_DAY] = mm
    return rain


def test_without_rain_the_source_gives_its_base_flow() -> None:
    series = LaggedRainSource(_spec()).simulate(np.zeros(DAYS))

    np.testing.assert_allclose(series.flow_m3_per_hour, BASE_FLOW)
    assert not series.muddy_water.any()


def test_rain_raises_the_flow_only_after_the_storm_starts() -> None:
    series = LaggedRainSource(_spec()).simulate(_single_storm(10.0))
    storm_start = RAIN_DAY * HOURS_PER_DAY

    assert np.all(series.flow_m3_per_hour[:storm_start] == BASE_FLOW)
    assert series.flow_m3_per_hour[storm_start] > BASE_FLOW


def test_response_decays_by_the_lag_constant_each_hour_once_rain_stops() -> None:
    series = LaggedRainSource(_spec()).simulate(_single_storm(10.0))
    # La lluvia del día cae en sus 24 horas; el decaimiento se mide desde el día siguiente.
    after_storm = (RAIN_DAY + 1) * HOURS_PER_DAY
    excess = series.flow_m3_per_hour - BASE_FLOW
    decay = math.exp(-1.0 / LAG_HOURS)

    ratio = excess[after_storm + 1 : after_storm + 3] / excess[after_storm : after_storm + 2]

    np.testing.assert_allclose(ratio, decay, rtol=1e-9)


def test_muddy_water_follows_a_strong_rain_day_for_the_set_duration() -> None:
    series = LaggedRainSource(_spec()).simulate(_single_storm(THRESHOLD_MM))
    storm_start = RAIN_DAY * HOURS_PER_DAY

    assert series.muddy_water[storm_start : storm_start + MUDDY_HOURS].all()
    assert not series.muddy_water[storm_start + MUDDY_HOURS]
    assert not series.muddy_water[:storm_start].any()


def test_light_rain_does_not_make_the_water_muddy() -> None:
    series = LaggedRainSource(_spec()).simulate(_single_storm(THRESHOLD_MM - 1.0))

    assert not series.muddy_water.any()


@settings(max_examples=50)
@given(
    rain=st.lists(
        st.floats(min_value=0.0, max_value=200.0, allow_nan=False),
        min_size=1,
        max_size=60,
    )
)
def test_flow_never_drops_below_base_and_is_finite(rain: list[float]) -> None:
    series = LaggedRainSource(_spec()).simulate(np.array(rain, dtype=np.float64))

    assert np.all(np.isfinite(series.flow_m3_per_hour))
    assert np.all(series.flow_m3_per_hour >= BASE_FLOW - 1e-12)


def test_negative_lag_is_rejected_by_the_model() -> None:
    with pytest.raises(ValueError, match="greater than 0"):
        _spec(response_lag_hours=0.0)
