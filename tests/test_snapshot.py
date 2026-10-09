"""Memento of the simulation run (P16): save, restore and determinism with the same seed."""

import dataclasses
from datetime import UTC, datetime, timedelta
from uuid import UUID

import numpy as np
import pytest

from caudal_sim.actuator_driver import SimulatedMotorDriver
from caudal_sim.command_channel import CommandLedger
from caudal_sim.event_bus import SimulationEventBus
from caudal_sim.scenario import TankSpec
from caudal_sim.simulation_step import SimulationStep, TankBalanceStep, ValveNodeStep
from caudal_sim.snapshot import SimulationRun, SimulationSnapshot
from caudal_sim.tank import Tank
from caudal_sim.valve_actuator import ValveActuator
from caudal_sim.valve_command_executor import ValveCommandExecutor
from caudal_sim.valve_commands import CloseValveCommand, OpenValveCommand
from caudal_sim.valve_state import ValveStatus

START = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
STEP = timedelta(seconds=30)
TRAVEL_TIME = timedelta(seconds=90)
MAX_TRAVEL_TIME = timedelta(minutes=5)
EXPIRES_AT = START + timedelta(hours=1)
OPEN_AT = START + timedelta(minutes=1)
CLOSE_AT = START + timedelta(minutes=20)
VALVE_ID = UUID("0190f3a2-7777-7000-8000-000000000002")
SEED = 42
OTHER_SEED = 7
TOTAL_STEPS = 10
SNAPSHOT_AFTER_STEPS = 4
INFLOW_M3_PER_HOUR = 1.0
OUTFLOW_M3_PER_HOUR = 0.25
TANK_SPEC = TankSpec(area_m2=10.0, gauge_min=0.0, gauge_max=5.0, gauge_step=0.1, initial_gauge=2.0)


class NoiseStep(SimulationStep):
    """Step that draws from the shared random generator, so the seed shows in the state."""

    def __init__(self, rng: np.random.Generator) -> None:
        self._rng = rng
        self.draws: list[float] = []

    def _advance(self, now: datetime, elapsed: timedelta) -> None:
        self.draws.append(float(self._rng.normal()))

    def capture(self) -> tuple[float, ...]:
        return tuple(self.draws)

    def restore(self, state: tuple[float, ...]) -> None:
        self.draws = list(state)


class Node:
    """A run with a valve, its ledger, executor, tank and a noisy step, built from one seed."""

    def __init__(self, seed: int) -> None:
        bus = SimulationEventBus()
        rng = np.random.Generator(np.random.PCG64(seed))
        self.ledger = CommandLedger(bus)
        self.ledger.enqueue(OpenValveCommand(UUID(int=1), VALVE_ID, OPEN_AT, EXPIRES_AT))
        self.ledger.enqueue(CloseValveCommand(UUID(int=2), VALVE_ID, CLOSE_AT, EXPIRES_AT))
        self.valve = ValveActuator(SimulatedMotorDriver(TRAVEL_TIME), MAX_TRAVEL_TIME)
        self.executor = ValveCommandExecutor(VALVE_ID, self.valve, self.ledger, bus)
        self.tank_step = TankBalanceStep(
            Tank(TANK_SPEC),
            lambda _at: INFLOW_M3_PER_HOUR,
            lambda _at: OUTFLOW_M3_PER_HOUR,
        )
        self.noise = NoiseStep(rng)
        self.run = SimulationRun(
            START,
            rng,
            steps=[ValveNodeStep(self.executor, self.valve), self.tank_step, self.noise],
            components=[self.valve, self.ledger, self.executor, self.tank_step, self.noise],
        )

    def advance(self, steps: int) -> None:
        for _ in range(steps):
            self.run.advance(STEP)


def _final_state(node: Node) -> SimulationSnapshot:
    return node.run.create_snapshot()


def test_restore_then_advance_matches_continuing_the_run() -> None:
    node = Node(SEED)
    node.advance(SNAPSHOT_AFTER_STEPS)
    snapshot = node.run.create_snapshot()
    node.advance(TOTAL_STEPS - SNAPSHOT_AFTER_STEPS)
    continued = _final_state(node)

    node.run.restore(snapshot)
    node.advance(TOTAL_STEPS - SNAPSHOT_AFTER_STEPS)

    assert _final_state(node) == continued


def test_snapshot_taken_mid_travel_restores_the_motor_and_the_valve() -> None:
    node = Node(SEED)
    node.advance(SNAPSHOT_AFTER_STEPS)
    snapshot = node.run.create_snapshot()
    assert node.valve.status is ValveStatus.OPENING

    node.advance(TOTAL_STEPS - SNAPSHOT_AFTER_STEPS)
    node.run.restore(snapshot)

    assert node.valve.status is ValveStatus.OPENING
    assert node.run.now == START + STEP * SNAPSHOT_AFTER_STEPS


def test_restored_run_equals_a_fresh_run_with_the_same_seed() -> None:
    first = Node(SEED)
    first.advance(TOTAL_STEPS)
    second = Node(SEED)
    second.advance(SNAPSHOT_AFTER_STEPS)
    snapshot = second.run.create_snapshot()
    second.advance(TOTAL_STEPS - SNAPSHOT_AFTER_STEPS)
    second.run.restore(snapshot)
    second.advance(TOTAL_STEPS - SNAPSHOT_AFTER_STEPS)

    assert _final_state(second) == _final_state(first)


def test_a_different_seed_gives_a_different_state() -> None:
    same = Node(SEED)
    same.advance(TOTAL_STEPS)
    other = Node(OTHER_SEED)
    other.advance(TOTAL_STEPS)

    assert _final_state(same).rng_state != _final_state(other).rng_state
    assert same.noise.draws != other.noise.draws


def test_snapshot_does_not_change_when_the_run_moves_on() -> None:
    node = Node(SEED)
    node.advance(SNAPSHOT_AFTER_STEPS)
    snapshot = node.run.create_snapshot()
    frozen_at = snapshot.at
    frozen_rng = dict(snapshot.rng_state)
    frozen_components = snapshot.component_states

    node.advance(TOTAL_STEPS)

    assert snapshot.at == frozen_at
    assert snapshot.rng_state == frozen_rng
    assert snapshot.component_states == frozen_components


def test_snapshot_is_immutable() -> None:
    snapshot = Node(SEED).run.create_snapshot()

    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.at = START  # type: ignore[misc]


def test_restore_refuses_a_snapshot_from_other_components() -> None:
    node = Node(SEED)
    snapshot = node.run.create_snapshot()
    smaller = SimulationSnapshot(
        at=snapshot.at,
        rng_state=snapshot.rng_state,
        component_states=snapshot.component_states[:-1],
    )

    with pytest.raises(ValueError, match="mismos componentes"):
        node.run.restore(smaller)


def test_ledger_restore_refuses_a_different_set_of_commands() -> None:
    ledger = CommandLedger()
    ledger.enqueue(OpenValveCommand(UUID(int=1), VALVE_ID, OPEN_AT, EXPIRES_AT))
    saved = ledger.capture()
    other = CommandLedger()
    other.enqueue(OpenValveCommand(UUID(int=9), VALVE_ID, OPEN_AT, EXPIRES_AT))

    with pytest.raises(ValueError, match="mismos comandos"):
        other.restore(saved)


def test_tank_volume_cannot_be_restored_above_its_capacity() -> None:
    tank = Tank(TANK_SPEC)

    with pytest.raises(ValueError, match="capacidad"):
        tank.restore_volume(tank.capacity_m3 + 1.0)


def test_valve_restore_refuses_a_negative_travel() -> None:
    valve = ValveActuator(SimulatedMotorDriver(TRAVEL_TIME), MAX_TRAVEL_TIME)
    state = valve.capture()

    with pytest.raises(ValueError, match="no puede ser negativo"):
        valve.restore(dataclasses.replace(state, travelled=-STEP))
