"""Tank mass balance tests (Hypothesis properties and concrete cases)."""

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from caudal_sim.builder import load_scenario
from caudal_sim.tank import Tank

NORMAL_YAML = Path(__file__).resolve().parents[1] / "scenarios" / "normal.yaml"
MASS_TOLERANCE_M3 = 1e-9
LEVEL_TOLERANCE_M = 1e-9
MAX_FLOW_M3_PER_HOUR = 5.0
MAX_STEPS = 48
FULL_TANK_MARGIN_M3 = 1.0


def _tank() -> Tank:
    return Tank(load_scenario(NORMAL_YAML).tank)


def test_capacity_is_area_times_the_gauge_maximum() -> None:
    spec = load_scenario(NORMAL_YAML).tank

    assert _tank().capacity_m3 == pytest.approx(spec.area_m2 * spec.gauge_max)


def test_closed_valve_delivers_nothing() -> None:
    tank = _tank()
    before = tank.volume_m3

    result = tank.step(inflow_m3=0.0, requested_outflow_m3=0.0)

    assert result.delivered_m3 == 0.0
    assert result.volume_m3 == pytest.approx(before)


def test_demand_is_trimmed_to_the_water_available() -> None:
    tank = _tank()
    available = tank.volume_m3

    result = tank.step(inflow_m3=0.0, requested_outflow_m3=available * 10)

    assert result.delivered_m3 == pytest.approx(available)
    assert result.volume_m3 == pytest.approx(0.0)


def test_water_above_capacity_leaves_as_overflow() -> None:
    tank = _tank()
    room = tank.capacity_m3 - tank.volume_m3

    result = tank.step(inflow_m3=room + FULL_TANK_MARGIN_M3, requested_outflow_m3=0.0)

    assert result.overflow_m3 == pytest.approx(FULL_TANK_MARGIN_M3)
    assert result.volume_m3 == pytest.approx(tank.capacity_m3)
    assert result.level_m == pytest.approx(load_scenario(NORMAL_YAML).tank.gauge_max)


def test_negative_flows_are_rejected() -> None:
    with pytest.raises(ValueError, match="no pueden ser negativas"):
        _tank().step(inflow_m3=-1.0, requested_outflow_m3=0.0)


@settings(max_examples=200)
@given(
    steps=st.lists(
        st.tuples(
            st.floats(min_value=0.0, max_value=MAX_FLOW_M3_PER_HOUR),
            st.floats(min_value=0.0, max_value=MAX_FLOW_M3_PER_HOUR),
        ),
        min_size=1,
        max_size=MAX_STEPS,
    )
)
def test_mass_balance_holds_and_volume_stays_within_bounds(
    steps: list[tuple[float, float]],
) -> None:
    tank = _tank()
    gauge_max = load_scenario(NORMAL_YAML).tank.gauge_max

    for inflow, requested in steps:
        before = tank.volume_m3
        result = tank.step(inflow_m3=inflow, requested_outflow_m3=requested)

        # Inflow = outflow + overflow + volume change (within numerical tolerance).
        balance = inflow - result.delivered_m3 - result.overflow_m3 - (result.volume_m3 - before)
        assert abs(balance) <= MASS_TOLERANCE_M3
        # Delivered water never exceeds the requested or the available amount.
        assert 0.0 <= result.delivered_m3 <= requested + MASS_TOLERANCE_M3
        assert result.overflow_m3 >= 0.0
        # Volume stays within [0, capacity], and the level within the gauge rule.
        assert -MASS_TOLERANCE_M3 <= result.volume_m3 <= tank.capacity_m3 + MASS_TOLERANCE_M3
        assert -LEVEL_TOLERANCE_M <= result.level_m <= gauge_max + LEVEL_TOLERANCE_M
