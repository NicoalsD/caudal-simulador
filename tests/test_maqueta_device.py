"""The virtual maqueta as a whole: telemetry batches, retries and its valves' command cycle."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from caudal_sim.maqueta_device import MaquetaDevice, MaquetaIdentities, build_maqueta_device
from caudal_sim.maqueta_spec import load_maqueta_spec
from caudal_sim.valve_state import ValveStatus
from maqueta_fake_api import VALVE_1, VALVE_1_DEVICE, MaquetaSetup, command_item, make_setup

INTERVAL_SECONDS = 10
POINTS_PER_INTERVAL = 10
SHORT_RUN_SECONDS = 4
RATE_LIMIT_ERRORS = 2
TICK_SECONDS = 1.0
RUN_SECONDS = 5
OPEN_RUN_SECONDS = 12
RUN_SECONDS_SHORT = 3
BATCHES_AFTER_RETRY = 2

SCENARIO = Path(__file__).resolve().parents[1] / "scenarios" / "maqueta.yaml"
START = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
BASE_URL = "http://api.test"


class StepClock:
    """Device time that moves only when the device sleeps, so no test waits."""

    def __init__(self, start: datetime) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def setup() -> MaquetaSetup:
    return make_setup()


def _device(setup: MaquetaSetup, clock: StepClock) -> MaquetaDevice:
    http = httpx.Client(base_url=BASE_URL, transport=setup.api.transport())
    identities: MaquetaIdentities = setup.identities
    return build_maqueta_device(
        load_maqueta_spec(SCENARIO), identities, http, clock=clock, sleeper=clock.sleep
    )


def test_the_telemetry_batches_the_level_points_of_each_interval(setup: MaquetaSetup) -> None:
    clock = StepClock(START)
    device = _device(setup, clock)

    device.run(seconds=10)

    assert len(setup.api.telemetry) == 1
    points = setup.api.telemetry[0]["points"]
    assert len(points) == POINTS_PER_INTERVAL
    assert {point["metric"] for point in points} == {"LEVEL"}
    for point in points:
        assert round(point["value"], 2) == point["value"]
        assert point["observed_at"].endswith("+00:00")
    assert device.report.batches_sent == 1


def test_every_telemetry_request_is_signed_by_the_sensor(setup: MaquetaSetup) -> None:
    _device(setup, StepClock(START)).run(seconds=10)

    telemetry = [request for request in setup.api.requests if request.path.endswith("/telemetry")]
    assert telemetry
    assert all(request.verified for request in telemetry)


def test_a_run_that_ends_early_still_sends_its_points(setup: MaquetaSetup) -> None:
    device = _device(setup, StepClock(START))

    device.run(seconds=3)

    assert len(setup.api.telemetry) == 1
    assert len(setup.api.telemetry[0]["points"]) == RUN_SECONDS_SHORT
    assert device.telemetry.pending == 0


def test_a_rate_limited_batch_is_kept_and_sent_on_the_next_pass(setup: MaquetaSetup) -> None:
    # The first send and every retry of the drain at the end of the run answer 429.
    setup.api.telemetry_statuses = [429] * (load_maqueta_spec(SCENARIO).buffer.max_attempts + 1)
    device = _device(setup, StepClock(START))

    device.run(seconds=10)
    assert setup.api.telemetry == []
    assert device.telemetry.pending == 1
    assert device.report.network_errors == 0

    device.run(seconds=10)

    assert device.telemetry.pending == 0
    assert len(setup.api.telemetry) == BATCHES_AFTER_RETRY
    first_batch, second_batch = (batch["points"] for batch in setup.api.telemetry)
    assert first_batch[-1]["observed_at"] < second_batch[0]["observed_at"]


def test_a_rate_limited_poll_is_counted_and_the_run_goes_on(setup: MaquetaSetup) -> None:
    setup.api.get_statuses = [429, 429]

    report = _device(setup, StepClock(START)).run(seconds=SHORT_RUN_SECONDS)

    assert report.ticks == SHORT_RUN_SECONDS
    assert report.network_errors == RATE_LIMIT_ERRORS
    assert "429" in report.last_error


def test_run_stops_after_the_requested_seconds(setup: MaquetaSetup) -> None:
    clock = StepClock(START)

    report = _device(setup, clock).run(seconds=RUN_SECONDS)

    assert report.ticks == RUN_SECONDS
    assert clock.sleeps == [TICK_SECONDS] * RUN_SECONDS


def test_an_open_command_opens_its_outlet_and_is_acked(setup: MaquetaSetup) -> None:
    setup.api.commands[str(VALVE_1_DEVICE)] = [
        command_item(
            "0190f3a2-7777-7000-8000-000000000021",
            VALVE_1,
            "OPEN",
            START - timedelta(minutes=1),
            START + timedelta(minutes=30),
        )
    ]
    device = _device(setup, StepClock(START))

    device.run(seconds=OPEN_RUN_SECONDS)

    assert device.outlets[0].actuator.status is ValveStatus.OPEN
    assert setup.api.acks[-1]["payload"]["result"] == "ACKED"


def test_a_refused_telemetry_batch_is_counted_and_not_retried(setup: MaquetaSetup) -> None:
    setup.api.telemetry_statuses = [422]
    device = _device(setup, StepClock(START))

    device.run(seconds=10)

    assert device.telemetry.pending == 0
    assert device.report.network_errors == 1
    assert device.report.batches_sent == 0
