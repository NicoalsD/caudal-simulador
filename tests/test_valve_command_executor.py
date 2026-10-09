"""Valve node that receives commands, moves its valve and confirms the result."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from caudal_sim.actuator_driver import SimulatedMotorDriver
from caudal_sim.command_channel import CommandLedger, CommandStatus
from caudal_sim.event_bus import SimulationEvent, SimulationEventBus, SimulationEventKind
from caudal_sim.valve_actuator import ValveActuator
from caudal_sim.valve_command_executor import (
    FAULT_DETAIL,
    REACHED_DETAIL,
    SUPERSEDED_DETAIL,
    ValveCommandExecutor,
)
from caudal_sim.valve_commands import CloseValveCommand, OpenValveCommand
from caudal_sim.valve_state import ValveStatus

VALVE_ID = UUID("0190f3a2-7777-7000-8000-000000000002")
OPEN_ID = UUID(int=1)
CLOSE_ID = UUID(int=2)
NOT_BEFORE = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
LATER_NOT_BEFORE = NOT_BEFORE + timedelta(minutes=1)
EXPIRES_AT = NOT_BEFORE + timedelta(minutes=10)
TRAVEL_TIME = timedelta(seconds=15)
MAX_TRAVEL_TIME = timedelta(seconds=60)


class Recorder:
    def __init__(self) -> None:
        self.events: list[SimulationEvent] = []

    def on_event(self, event: SimulationEvent) -> None:
        self.events.append(event)


class Node:
    """A ledger, a valve and its executor, wired as in the simulation."""

    def __init__(self, *, stalled: bool = False) -> None:
        self.bus = SimulationEventBus()
        self.recorder = Recorder()
        self.bus.subscribe(self.recorder)
        self.ledger = CommandLedger(self.bus)
        self.driver = SimulatedMotorDriver(TRAVEL_TIME, stalled=stalled)
        self.valve = ValveActuator(self.driver, MAX_TRAVEL_TIME)
        self.executor = ValveCommandExecutor(VALVE_ID, self.valve, self.ledger, self.bus)

    def poll(self, now: datetime) -> None:
        self.executor.poll(now)


def test_open_command_moves_the_valve_and_is_confirmed_when_it_arrives() -> None:
    node = Node()
    node.ledger.enqueue(OpenValveCommand(OPEN_ID, VALVE_ID, NOT_BEFORE, EXPIRES_AT))

    node.poll(NOT_BEFORE)
    assert node.valve.status is ValveStatus.OPENING
    assert node.ledger.status_of(OPEN_ID) is CommandStatus.DELIVERED

    node.valve.advance(TRAVEL_TIME)
    node.poll(NOT_BEFORE + TRAVEL_TIME)

    assert node.ledger.status_of(OPEN_ID) is CommandStatus.ACKED
    assert node.ledger.ack_detail_of(OPEN_ID) == REACHED_DETAIL
    kinds = [event.kind for event in node.recorder.events]
    assert SimulationEventKind.VALVE_STATE_CHANGED in kinds
    assert kinds[-1] is SimulationEventKind.COMMAND_CONFIRMED


def test_in_flight_command_is_not_applied_again_on_redelivery() -> None:
    node = Node()
    node.ledger.enqueue(OpenValveCommand(OPEN_ID, VALVE_ID, NOT_BEFORE, EXPIRES_AT))
    node.poll(NOT_BEFORE)
    node.valve.advance(TRAVEL_TIME / 2)

    node.poll(NOT_BEFORE)

    assert node.valve.status is ValveStatus.OPENING
    assert node.driver.direction is not None


def test_stalled_valve_confirms_failure_with_the_fault_detail() -> None:
    node = Node(stalled=True)
    node.ledger.enqueue(OpenValveCommand(OPEN_ID, VALVE_ID, NOT_BEFORE, EXPIRES_AT))
    node.poll(NOT_BEFORE)

    node.valve.advance(MAX_TRAVEL_TIME)
    node.poll(NOT_BEFORE + MAX_TRAVEL_TIME)

    assert node.valve.status is ValveStatus.FAULT
    assert node.ledger.status_of(OPEN_ID) is CommandStatus.FAILED
    assert node.ledger.ack_detail_of(OPEN_ID) == FAULT_DETAIL


def test_newest_of_two_conflicting_commands_wins_and_the_other_is_superseded() -> None:
    node = Node()
    node.ledger.enqueue(OpenValveCommand(OPEN_ID, VALVE_ID, NOT_BEFORE, EXPIRES_AT))
    node.ledger.enqueue(CloseValveCommand(CLOSE_ID, VALVE_ID, LATER_NOT_BEFORE, EXPIRES_AT))

    node.poll(LATER_NOT_BEFORE)

    assert node.valve.status is ValveStatus.CLOSED
    assert node.driver.direction is None
    assert node.ledger.status_of(CLOSE_ID) is CommandStatus.ACKED
    assert node.ledger.status_of(OPEN_ID) is CommandStatus.FAILED
    assert node.ledger.ack_detail_of(OPEN_ID) == SUPERSEDED_DETAIL


def test_command_received_after_its_expiry_does_not_move_the_valve() -> None:
    node = Node()
    node.ledger.enqueue(OpenValveCommand(OPEN_ID, VALVE_ID, NOT_BEFORE, EXPIRES_AT))

    node.poll(EXPIRES_AT + timedelta(seconds=1))

    assert node.valve.status is ValveStatus.CLOSED
    assert node.ledger.status_of(OPEN_ID) is CommandStatus.EXPIRED


def test_no_valve_event_is_published_when_the_valve_does_not_move() -> None:
    node = Node()
    node.ledger.enqueue(CloseValveCommand(CLOSE_ID, VALVE_ID, NOT_BEFORE, EXPIRES_AT))

    node.poll(NOT_BEFORE)
    node.poll(NOT_BEFORE)

    assert [event.kind for event in node.recorder.events] == [
        SimulationEventKind.COMMAND_DELIVERED,
        SimulationEventKind.COMMAND_CONFIRMED,
    ]
