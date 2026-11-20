"""Commands of a maqueta outlet: the GET, the run of OPEN and CLOSE, and the ack of each one."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from caudal_sim.actuator_driver import SimulatedMotorDriver
from caudal_sim.event_bus import SimulationEventBus
from caudal_sim.maqueta_commands import UNKNOWN_COMMAND_DETAIL, HttpCommandSource
from caudal_sim.telemetry_transport import (
    DeviceIdentity,
    SignedHttpTransport,
    TransportRejectedError,
)
from caudal_sim.valve_actuator import ValveActuator
from caudal_sim.valve_command_executor import REACHED_DETAIL, ValveCommandExecutor
from caudal_sim.valve_state import ValveStatus
from maqueta_fake_api import (
    VALVE_1,
    VALVE_1_DEVICE,
    FakeApi,
    command_item,
    make_setup,
)

BASE_URL = "http://api.test"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
TRAVEL = timedelta(seconds=3)
MAX_TRAVEL = timedelta(seconds=6)
ONE_SECOND = timedelta(seconds=1)
ORDER_ID = "0190f3a2-7777-7000-8000-000000000001"
OTHER_ORDER_ID = "0190f3a2-7777-7000-8000-000000000002"


class Outlet:
    """One outlet wired like the device does: source, actuator and executor."""

    def __init__(self, api: FakeApi, identity: DeviceIdentity, valve_id: UUID) -> None:
        http = httpx.Client(base_url=BASE_URL, transport=api.transport())
        self.source = HttpCommandSource(
            SignedHttpTransport(http, identity), valve_id, datetime.fromisoformat
        )
        self.actuator = ValveActuator(SimulatedMotorDriver(TRAVEL), MAX_TRAVEL)
        self.executor = ValveCommandExecutor(
            valve_id, self.actuator, self.source, SimulationEventBus()
        )

    def poll_and_wait(self, seconds: int, now: datetime = NOW) -> None:
        for second in range(seconds):
            self.executor.poll(now + timedelta(seconds=second))
            self.actuator.advance(ONE_SECOND)


def _outlet_one(api: FakeApi, identity: DeviceIdentity) -> Outlet:
    return Outlet(api, identity, VALVE_1)


def test_an_open_command_moves_the_valve_and_is_acked_when_it_reaches_open() -> None:
    setup = make_setup()
    api = setup.api
    api.commands[str(VALVE_1_DEVICE)] = [
        command_item(
            ORDER_ID, VALVE_1, "OPEN", NOW - timedelta(minutes=1), NOW + timedelta(minutes=10)
        )
    ]
    outlet = _outlet_one(api, setup.identities.outlets[0][0])

    outlet.poll_and_wait(6)

    assert outlet.actuator.status is ValveStatus.OPEN
    assert len(api.acks) == 1
    assert api.acks[0]["command_id"] == ORDER_ID
    assert api.acks[0]["payload"] == {"result": "ACKED", "detail": REACHED_DETAIL}


def test_a_close_command_closes_an_open_valve() -> None:
    setup = make_setup()
    api = setup.api
    outlet = _outlet_one(api, setup.identities.outlets[0][0])
    outlet.actuator.request_open()
    outlet.poll_and_wait(4)
    api.commands[str(VALVE_1_DEVICE)] = [
        command_item(
            ORDER_ID, VALVE_1, "CLOSE", NOW - timedelta(minutes=1), NOW + timedelta(minutes=10)
        )
    ]

    outlet.poll_and_wait(6, now=NOW + timedelta(minutes=5))

    assert outlet.actuator.status is ValveStatus.CLOSED
    assert api.acks[-1]["payload"]["result"] == "ACKED"


def test_an_unknown_action_is_acked_as_failed_and_the_valve_does_not_move() -> None:
    setup = make_setup()
    api = setup.api
    api.commands[str(VALVE_1_DEVICE)] = [
        command_item(
            ORDER_ID, VALVE_1, "TOGGLE", NOW - timedelta(minutes=1), NOW + timedelta(minutes=10)
        )
    ]
    outlet = _outlet_one(api, setup.identities.outlets[0][0])

    outlet.poll_and_wait(2)

    assert outlet.actuator.status is ValveStatus.CLOSED
    assert api.acks == [
        {
            "device": str(VALVE_1_DEVICE),
            "command_id": ORDER_ID,
            "body": api.acks[0]["body"],
            "payload": {"result": "FAILED", "detail": UNKNOWN_COMMAND_DETAIL},
        }
    ]


def test_a_command_for_another_valve_is_acked_as_failed() -> None:
    setup = make_setup()
    api = setup.api
    stranger = uuid4()
    api.commands[str(VALVE_1_DEVICE)] = [
        command_item(
            ORDER_ID, stranger, "OPEN", NOW - timedelta(minutes=1), NOW + timedelta(minutes=10)
        )
    ]
    outlet = _outlet_one(api, setup.identities.outlets[0][0])

    outlet.poll_and_wait(2)

    assert outlet.actuator.status is ValveStatus.CLOSED
    assert api.acks[0]["payload"]["result"] == "FAILED"


def test_a_command_past_its_expiration_is_neither_run_nor_acked() -> None:
    setup = make_setup()
    api = setup.api
    api.commands[str(VALVE_1_DEVICE)] = [
        command_item(
            ORDER_ID, VALVE_1, "OPEN", NOW - timedelta(minutes=20), NOW - timedelta(seconds=1)
        )
    ]
    outlet = _outlet_one(api, setup.identities.outlets[0][0])

    outlet.poll_and_wait(4)

    assert outlet.actuator.status is ValveStatus.CLOSED
    assert api.acks == []


def test_a_redelivered_command_is_not_run_twice_while_the_valve_moves() -> None:
    setup = make_setup()
    api = setup.api
    api.commands[str(VALVE_1_DEVICE)] = [
        command_item(
            ORDER_ID, VALVE_1, "OPEN", NOW - timedelta(minutes=1), NOW + timedelta(minutes=10)
        )
    ]
    outlet = _outlet_one(api, setup.identities.outlets[0][0])

    outlet.executor.poll(NOW)
    outlet.actuator.advance(ONE_SECOND)
    outlet.executor.poll(NOW + ONE_SECOND)
    outlet.actuator.advance(ONE_SECOND)

    assert outlet.actuator.capture().travelled == 2 * ONE_SECOND
    assert outlet.actuator.status is ValveStatus.OPENING


def test_a_conflict_on_ack_is_counted_and_does_not_stop_the_source() -> None:
    setup = make_setup()
    api = setup.api
    api.ack_status = 409
    api.commands[str(VALVE_1_DEVICE)] = [
        command_item(
            ORDER_ID, VALVE_1, "OPEN", NOW - timedelta(minutes=1), NOW + timedelta(minutes=10)
        )
    ]
    outlet = _outlet_one(api, setup.identities.outlets[0][0])

    outlet.poll_and_wait(6)

    assert outlet.source.network_errors >= 1
    assert "INVALID_STATE_TRANSITION" in outlet.source.last_error


def test_a_failed_get_raises_for_the_device_to_count() -> None:
    setup = make_setup()
    api = setup.api
    api.get_statuses = [429]
    outlet = _outlet_one(api, setup.identities.outlets[0][0])

    with pytest.raises(TransportRejectedError, match="429"):
        outlet.executor.poll(NOW)


def test_a_valve_id_that_is_not_the_outlet_returns_no_commands() -> None:
    setup = make_setup()
    outlet = _outlet_one(setup.api, setup.identities.outlets[0][0])

    assert outlet.source.deliver(uuid4(), NOW) == ()


def test_the_command_ids_in_the_ack_path_are_the_ones_of_the_get() -> None:
    setup = make_setup()
    api = setup.api
    api.commands[str(VALVE_1_DEVICE)] = [
        command_item(
            OTHER_ORDER_ID, VALVE_1, "OPEN", NOW - timedelta(minutes=1), NOW + timedelta(minutes=10)
        )
    ]
    outlet = _outlet_one(api, setup.identities.outlets[0][0])

    outlet.poll_and_wait(6)

    assert api.acks[-1]["command_id"] == OTHER_ORDER_ID
