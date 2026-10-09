"""Template Method of the simulation step (P20): fixed order and the two concrete steps."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from caudal_sim.actuator_driver import SimulatedMotorDriver
from caudal_sim.command_channel import CommandLedger, CommandStatus
from caudal_sim.event_bus import SimulationEventBus
from caudal_sim.scenario import TankSpec
from caudal_sim.simulation_step import SimulationStep, TankBalanceStep, ValveNodeStep
from caudal_sim.tank import Tank
from caudal_sim.valve_actuator import ValveActuator
from caudal_sim.valve_command_executor import ValveCommandExecutor
from caudal_sim.valve_commands import OpenValveCommand
from caudal_sim.valve_state import ValveStatus

START = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
ONE_MINUTE = timedelta(minutes=1)
ONE_HOUR = timedelta(hours=1)
THIRTY_SECONDS = timedelta(seconds=30)
TRAVEL_TIME = timedelta(seconds=60)
MAX_TRAVEL_TIME = timedelta(minutes=5)
VALVE_ID = UUID("0190f3a2-7777-7000-8000-000000000002")
EXPIRES_AT = START + timedelta(hours=1)
AREA_M2 = 10.0
GAUGE_MAX_M = 5.0
INITIAL_GAUGE_M = 2.0
INFLOW_M3_PER_HOUR = 1.0
OUTFLOW_M3_PER_HOUR = 0.5
TANK_SPEC = TankSpec(
    area_m2=AREA_M2,
    gauge_min=0.0,
    gauge_max=GAUGE_MAX_M,
    gauge_step=0.1,
    initial_gauge=INITIAL_GAUGE_M,
)


class RecordingStep(SimulationStep):
    """Test step that records the order in which the template calls its methods."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _receive(self, now: datetime) -> None:
        self.calls.append("receive")

    def _advance(self, now: datetime, elapsed: timedelta) -> None:
        self.calls.append("advance")

    def _report(self, end: datetime) -> None:
        self.calls.append("report")


def test_template_calls_receive_then_advance_then_report() -> None:
    step = RecordingStep()

    end = step.run(START, ONE_MINUTE)

    assert step.calls == ["receive", "advance", "report"]
    assert end == START + ONE_MINUTE


def test_template_refuses_a_step_that_does_not_advance_time() -> None:
    step = RecordingStep()

    with pytest.raises(ValueError, match="avanzar tiempo"):
        step.run(START, timedelta(0))
    assert step.calls == []


def test_run_is_final_so_subclasses_cannot_reorder_the_steps() -> None:
    assert SimulationStep.run.__final__ is True  # type: ignore[attr-defined]


def test_valve_node_step_confirms_an_order_received_during_the_run() -> None:
    bus = SimulationEventBus()
    ledger = CommandLedger(bus)
    driver = SimulatedMotorDriver(TRAVEL_TIME)
    valve = ValveActuator(driver, MAX_TRAVEL_TIME)
    executor = ValveCommandExecutor(VALVE_ID, valve, ledger, bus)
    command = OpenValveCommand(UUID(int=1), VALVE_ID, START, EXPIRES_AT)
    ledger.enqueue(command)
    step = ValveNodeStep(executor, valve)

    step.run(START, THIRTY_SECONDS)
    assert valve.status is ValveStatus.OPENING
    assert ledger.status_of(command.command_id) is CommandStatus.DELIVERED

    step.run(START + THIRTY_SECONDS, THIRTY_SECONDS)
    assert valve.status is ValveStatus.OPEN
    assert ledger.status_of(command.command_id) is CommandStatus.ACKED


def test_tank_balance_step_matches_the_tank_run_directly() -> None:
    stepped = Tank(TANK_SPEC)
    direct = Tank(TANK_SPEC)
    step = TankBalanceStep(
        stepped,
        lambda _at: INFLOW_M3_PER_HOUR,
        lambda _at: OUTFLOW_M3_PER_HOUR,
    )

    step.run(START, ONE_HOUR)
    step.run(START + ONE_HOUR, ONE_HOUR)
    direct.step(INFLOW_M3_PER_HOUR, OUTFLOW_M3_PER_HOUR)
    direct_result = direct.step(INFLOW_M3_PER_HOUR, OUTFLOW_M3_PER_HOUR)

    assert step.last_result is not None
    assert step.last_result.volume_m3 == pytest.approx(direct_result.volume_m3)


def test_tank_balance_step_scales_the_flows_to_the_length_of_the_step() -> None:
    tank = Tank(TANK_SPEC)
    step = TankBalanceStep(tank, lambda _at: INFLOW_M3_PER_HOUR, lambda _at: 0.0)

    step.run(START, THIRTY_SECONDS)

    expected_volume = AREA_M2 * INITIAL_GAUGE_M + INFLOW_M3_PER_HOUR * (THIRTY_SECONDS / ONE_HOUR)
    assert step.last_result is not None
    assert step.last_result.volume_m3 == pytest.approx(expected_volume)
