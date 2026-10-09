"""Server side of valve commands: delivery, expiry and confirmation (P13 and section 5.2)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from caudal_sim.command_channel import (
    MAX_ACK_DETAIL_LENGTH,
    MAX_COMMANDS_PER_DELIVERY,
    AckResult,
    CommandLedger,
    CommandNotFoundError,
    CommandStatus,
    InvalidCommandTransitionError,
)
from caudal_sim.event_bus import SimulationEvent, SimulationEventBus, SimulationEventKind
from caudal_sim.valve_commands import CloseValveCommand, OpenValveCommand, ValveCommand

VALVE_ID = UUID("0190f3a2-7777-7000-8000-000000000002")
OTHER_VALVE_ID = UUID("0190f3a2-7777-7000-8000-000000000003")
NOT_BEFORE = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
EXPIRES_AT = NOT_BEFORE + timedelta(minutes=10)
BEFORE_START = NOT_BEFORE - timedelta(seconds=1)
INSIDE = NOT_BEFORE + timedelta(minutes=5)
AFTER_EXPIRY = EXPIRES_AT + timedelta(seconds=1)
DETAIL = "Válvula abierta; posición confirmada."


def _command(number: int, *, valve_id: UUID = VALVE_ID) -> OpenValveCommand:
    return OpenValveCommand(
        UUID(int=number),
        valve_id,
        NOT_BEFORE,
        EXPIRES_AT,
    )


class Recorder:
    def __init__(self) -> None:
        self.events: list[SimulationEvent] = []

    def on_event(self, event: SimulationEvent) -> None:
        self.events.append(event)


def _ledger_with_recorder() -> tuple[CommandLedger, Recorder]:
    bus = SimulationEventBus()
    recorder = Recorder()
    bus.subscribe(recorder)
    return CommandLedger(bus), recorder


def test_command_is_not_delivered_before_its_start() -> None:
    ledger, _ = _ledger_with_recorder()
    command = _command(1)
    ledger.enqueue(command)

    assert ledger.deliver(VALVE_ID, BEFORE_START) == ()
    assert ledger.status_of(command.command_id) is CommandStatus.PENDING


def test_first_delivery_marks_the_command_and_publishes_an_event() -> None:
    ledger, recorder = _ledger_with_recorder()
    command = _command(1)
    ledger.enqueue(command)

    delivered = ledger.deliver(VALVE_ID, INSIDE)

    assert delivered == (command,)
    assert ledger.status_of(command.command_id) is CommandStatus.DELIVERED
    assert [event.kind for event in recorder.events] == [SimulationEventKind.COMMAND_DELIVERED]


def test_unconfirmed_command_is_delivered_again_while_valid() -> None:
    ledger, _ = _ledger_with_recorder()
    command = _command(1)
    ledger.enqueue(command)
    ledger.deliver(VALVE_ID, INSIDE)

    assert ledger.deliver(VALVE_ID, INSIDE) == (command,)


def test_commands_of_other_valves_are_not_delivered() -> None:
    ledger, _ = _ledger_with_recorder()
    ledger.enqueue(_command(1, valve_id=OTHER_VALVE_ID))

    assert ledger.deliver(VALVE_ID, INSIDE) == ()


def test_expired_command_is_marked_and_never_delivered() -> None:
    ledger, _ = _ledger_with_recorder()
    command = _command(1)
    ledger.enqueue(command)

    assert ledger.deliver(VALVE_ID, AFTER_EXPIRY) == ()
    assert ledger.status_of(command.command_id) is CommandStatus.EXPIRED
    assert ledger.deliver(VALVE_ID, INSIDE) == ()


def test_expiry_also_applies_to_delivered_commands_without_confirmation() -> None:
    ledger, _ = _ledger_with_recorder()
    command = _command(1)
    ledger.enqueue(command)
    ledger.deliver(VALVE_ID, INSIDE)

    ledger.expire_due(AFTER_EXPIRY)

    assert ledger.status_of(command.command_id) is CommandStatus.EXPIRED


def test_delivery_returns_at_most_the_protocol_limit_oldest_first() -> None:
    ledger, _ = _ledger_with_recorder()
    commands = [_command(number) for number in range(1, MAX_COMMANDS_PER_DELIVERY + 2)]
    for command in commands:
        ledger.enqueue(command)

    delivered = ledger.deliver(VALVE_ID, INSIDE)

    assert len(delivered) == MAX_COMMANDS_PER_DELIVERY


def test_acknowledgement_confirms_a_delivered_command_and_publishes_it() -> None:
    ledger, recorder = _ledger_with_recorder()
    command = _command(1)
    ledger.enqueue(command)
    ledger.deliver(VALVE_ID, INSIDE)

    ledger.acknowledge(command.command_id, AckResult.ACKED, DETAIL, INSIDE)

    assert ledger.status_of(command.command_id) is CommandStatus.ACKED
    assert ledger.ack_detail_of(command.command_id) == DETAIL
    assert recorder.events[-1].kind is SimulationEventKind.COMMAND_CONFIRMED
    assert ledger.deliver(VALVE_ID, INSIDE) == ()


def test_repeating_the_same_acknowledgement_changes_nothing() -> None:
    ledger, _ = _ledger_with_recorder()
    command = _command(1)
    ledger.enqueue(command)
    ledger.deliver(VALVE_ID, INSIDE)
    ledger.acknowledge(command.command_id, AckResult.FAILED, DETAIL, INSIDE)

    ledger.acknowledge(command.command_id, AckResult.FAILED, DETAIL, INSIDE)

    assert ledger.status_of(command.command_id) is CommandStatus.FAILED


def test_contradicting_acknowledgement_is_rejected() -> None:
    ledger, _ = _ledger_with_recorder()
    command = _command(1)
    ledger.enqueue(command)
    ledger.deliver(VALVE_ID, INSIDE)
    ledger.acknowledge(command.command_id, AckResult.ACKED, DETAIL, INSIDE)

    with pytest.raises(InvalidCommandTransitionError):
        ledger.acknowledge(command.command_id, AckResult.FAILED, DETAIL, INSIDE)


@pytest.mark.parametrize("status_source", ["expired", "pending", "cancelled"])
def test_acknowledgement_of_a_command_not_delivered_is_rejected(status_source: str) -> None:
    ledger, _ = _ledger_with_recorder()
    command = _command(1)
    ledger.enqueue(command)
    if status_source == "expired":
        ledger.expire_due(AFTER_EXPIRY)
    elif status_source == "cancelled":
        ledger.cancel(command.command_id)

    with pytest.raises(InvalidCommandTransitionError):
        ledger.acknowledge(command.command_id, AckResult.ACKED, DETAIL, INSIDE)


def test_unknown_command_and_long_detail_are_rejected() -> None:
    ledger, _ = _ledger_with_recorder()
    command = _command(1)
    ledger.enqueue(command)
    ledger.deliver(VALVE_ID, INSIDE)

    with pytest.raises(CommandNotFoundError):
        ledger.acknowledge(UUID(int=99), AckResult.ACKED, DETAIL, INSIDE)
    with pytest.raises(ValueError, match="no puede superar"):
        ledger.acknowledge(
            command.command_id, AckResult.ACKED, "x" * (MAX_ACK_DETAIL_LENGTH + 1), INSIDE
        )


def test_only_a_pending_command_can_be_cancelled() -> None:
    ledger, _ = _ledger_with_recorder()
    pending = _command(1, valve_id=OTHER_VALVE_ID)
    delivered = _command(2)
    ledger.enqueue(pending)
    ledger.enqueue(delivered)
    ledger.deliver(VALVE_ID, INSIDE)

    ledger.cancel(pending.command_id)

    assert ledger.status_of(pending.command_id) is CommandStatus.CANCELLED
    with pytest.raises(InvalidCommandTransitionError):
        ledger.cancel(delivered.command_id)


def test_duplicate_command_identifier_is_rejected() -> None:
    ledger, _ = _ledger_with_recorder()
    ledger.enqueue(_command(1))

    with pytest.raises(ValueError, match="ya está en la cola"):
        ledger.enqueue(CloseValveCommand(UUID(int=1), VALVE_ID, NOT_BEFORE, EXPIRES_AT))


def test_ledger_works_without_a_bus() -> None:
    ledger = CommandLedger()
    command: ValveCommand = _command(1)
    ledger.enqueue(command)

    assert ledger.deliver(VALVE_ID, INSIDE) == (command,)
