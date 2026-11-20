"""Physics of the maqueta: outflow of the orifices, float with hysteresis, overflow and balance."""

import math
from pathlib import Path

import pytest

from caudal_sim.maqueta_plant import (
    GRAVITY_M_PER_S2,
    METERS_PER_INCH,
    FloatSwitch,
    MaquetaPlant,
    MaquetaPlantBuilder,
    Outlet,
)
from caudal_sim.maqueta_spec import MaquetaSpec, load_maqueta_spec

SCENARIO = Path(__file__).resolve().parents[1] / "scenarios" / "maqueta.yaml"
ONE_SECOND = 1.0
RESTART_LEVEL_M = 0.26
BALANCE_POINT_M = 0.157
BALANCE_TOLERANCE_M = 0.002
ONE_OUTLET_MAX_M = 0.31
ONE_OUTLET_MIN_M = 0.25
BOTH_OPEN = (1.0, 1.0)
CLOSED = (0.0, 0.0)
M3_PER_S_TO_L_PER_MIN = 60_000.0  # 1 m³/s is 60 000 L/min
DIAMETER_M = 0.25 * METERS_PER_INCH


def _spec(**tank: float | bool) -> MaquetaSpec:
    spec = load_maqueta_spec(SCENARIO)
    return spec.model_copy(update={"tank": spec.tank.model_copy(update=tank)})


def _plant(initial_level_m: float | None = None, *, pump_on: bool = True) -> MaquetaPlant:
    builder = MaquetaPlantBuilder(load_maqueta_spec(SCENARIO)).with_pump_on(pump_on)
    if initial_level_m is not None:
        builder.with_initial_level(initial_level_m)
    return builder.build()


def _drain_plant(level_m: float) -> MaquetaPlant:
    """Pump off for good (restart level at zero), to watch the outlets alone."""
    spec = _spec(float_restart_m=0.0)
    return MaquetaPlantBuilder(spec).with_initial_level(level_m).with_pump_on(False).build()


def test_outlet_flow_at_the_overflow_height_follows_the_orifice_formula() -> None:
    outlet = Outlet(DIAMETER_M, discharge_coefficient=0.6)
    expected_m3_per_s = 0.6 * math.pi * DIAMETER_M**2 / 4 * math.sqrt(2 * GRAVITY_M_PER_S2 * 0.32)

    flow = outlet.flow_m3_per_s(0.32, opening=1.0)

    assert flow == pytest.approx(expected_m3_per_s)
    assert flow * M3_PER_S_TO_L_PER_MIN == pytest.approx(2.85, abs=0.01)


def test_outflow_grows_with_the_square_root_of_the_level() -> None:
    outlet = Outlet(DIAMETER_M, discharge_coefficient=0.6)

    ratio = outlet.flow_m3_per_s(0.30, 1.0) / outlet.flow_m3_per_s(0.10, 1.0)

    assert ratio == pytest.approx(math.sqrt(3.0))


def test_a_closed_outlet_or_an_empty_tank_gives_no_outflow() -> None:
    outlet = Outlet(DIAMETER_M, discharge_coefficient=0.6)

    assert outlet.flow_m3_per_s(0.30, 0.0) == 0.0
    assert outlet.flow_m3_per_s(0.0, 1.0) == 0.0


def test_a_full_tank_drains_faster_than_a_low_one() -> None:
    high = _drain_plant(0.30)
    low = _drain_plant(0.10)

    drop_high = high.level_m - high.advance(ONE_SECOND, BOTH_OPEN).level_m
    drop_low = low.level_m - low.advance(ONE_SECOND, BOTH_OPEN).level_m

    assert drop_high > drop_low > 0


def test_the_pump_is_cut_by_the_high_float_and_restarts_under_the_restart_level() -> None:
    plant = _plant(0.10)
    while plant.pump_on:
        plant.advance(ONE_SECOND, CLOSED)
    cut_level = plant.level_m

    for _ in range(100):
        step = plant.advance(ONE_SECOND, CLOSED)

    assert not step.pump_on
    assert cut_level == pytest.approx(0.30, abs=0.001)
    assert plant.level_m == pytest.approx(cut_level)

    for _ in range(600):
        plant.advance(ONE_SECOND, BOTH_OPEN)
        if plant.pump_on:
            break

    assert plant.pump_on
    assert plant.level_m < RESTART_LEVEL_M


def test_with_both_outlets_open_the_level_settles_near_the_balance_point() -> None:
    plant = _plant(0.10)

    for _ in range(20_000):
        plant.advance(ONE_SECOND, BOTH_OPEN)

    # Inflow balances both outlets: Q_in = 2 * Cd * A * sqrt(2 g h). By hand, the level is 0.157 m.
    assert abs(plant.level_m - BALANCE_POINT_M) <= BALANCE_TOLERANCE_M


def test_with_one_outlet_open_and_the_float_working_the_pump_cycles_below_the_overflow() -> None:
    plant = _plant(0.10)
    levels = [plant.advance(ONE_SECOND, (1.0, 0.0)).level_m for _ in range(3_000)]

    late = levels[1_000:]
    assert max(late) <= ONE_OUTLET_MAX_M
    assert min(late) >= ONE_OUTLET_MIN_M


def test_without_a_float_cut_the_tank_fills_to_the_overflow_and_the_excess_spills() -> None:
    spec = _spec(float_high_m=0.35)
    plant = MaquetaPlantBuilder(spec).with_initial_level(0.10).build()
    spilled = 0.0

    for _ in range(600):
        step = plant.advance(ONE_SECOND, CLOSED)
        spilled += step.overflow_m3

    assert plant.level_m == pytest.approx(0.32)
    assert spilled > 0


def test_the_volume_balance_closes_at_every_step() -> None:
    plant = _plant(0.10)
    area = load_maqueta_spec(SCENARIO).tank.area_m2
    start_volume = plant.level_m * area
    inflow = delivered = overflow = 0.0

    for index in range(2_000):
        openings = (1.0, 0.0) if index % 2 else (0.0, 1.0)
        step = plant.advance(ONE_SECOND, openings)
        inflow += step.inflow_m3
        delivered += step.delivered_m3
        overflow += step.overflow_m3

    end_volume = plant.level_m * area
    assert end_volume == pytest.approx(start_volume + inflow - delivered - overflow, abs=1e-12)


def test_the_pump_flow_is_four_liters_per_minute() -> None:
    plant = _plant(0.10)

    step = plant.advance(60.0, CLOSED)

    # One minute at 4 L/min is 4 liters, which is 0.004 m³.
    assert step.inflow_m3 == pytest.approx(0.004)


def test_the_float_switch_keeps_its_state_between_the_two_levels() -> None:
    float_switch = FloatSwitch(high_m=0.30, restart_m=0.26, pump_on=True)

    assert float_switch.update(0.28) is True
    assert float_switch.update(0.30) is False
    assert float_switch.update(0.28) is False
    assert float_switch.update(0.25) is True


def test_a_float_with_the_restart_above_the_high_level_is_rejected() -> None:
    with pytest.raises(ValueError):
        FloatSwitch(high_m=0.30, restart_m=0.31)


def test_the_builder_applies_the_overrides_and_keeps_the_scenario_intact() -> None:
    spec = load_maqueta_spec(SCENARIO)
    plant = MaquetaPlantBuilder(spec).with_initial_level(0.20).with_pump_on(False).build()

    assert plant.level_m == pytest.approx(0.20)
    assert plant.pump_on is False
    assert spec.tank.initial_level_m == pytest.approx(0.10)
