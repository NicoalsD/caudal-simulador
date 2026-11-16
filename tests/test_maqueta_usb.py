"""The USB maqueta: the line protocol of the UNO and the device loop over a fake board."""

from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from caudal_sim.maqueta_device import MaquetaDevice
from caudal_sim.maqueta_usb import (
    UsbSensorSpec,
    build_usb_maqueta_device,
    load_usb_spec,
    save_usb_spec,
)
from caudal_sim.serial_link import SerialLink, SerialLinkError
from caudal_sim.valve_state import ValveStatus
from maqueta_fake_api import VALVE_1, VALVE_1_DEVICE, MaquetaSetup, command_item, make_setup

CONFIG = Path(__file__).resolve().parents[1] / "scenarios" / "maqueta-usb.yaml"
START = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
BASE_URL = "http://api.test"
EMPTY_MM = 350
FULL_MM = 80
WATER_MM = 200
OPEN_RUN_SECONDS = 6
LEVEL_AT_WATER_M = 0.15


class FakeUno:
    """Answers like the firmware of `caudal-maqueta/uno`. Servos arrive at once."""

    def __init__(self, distance_mm: int = WATER_MM, *, servo_answers: bool = True) -> None:
        self.distance_mm = distance_mm
        self.servo_answers = servo_answers
        self.written: list[str] = []
        self.angles = {1: -1, 2: -1}
        self._out: deque[bytes] = deque([b"READY caudal-uno 1.0.0\n"])

    def write(self, data: bytes, /) -> int:
        command = data.decode().strip()
        self.written.append(command)
        self._answer(command)
        return len(data)

    def readline(self) -> bytes:
        return self._out.popleft() if self._out else b""

    def close(self) -> None:
        return

    def _say(self, text: str) -> None:
        self._out.append(f"{text}\n".encode())

    def _answer(self, command: str) -> None:
        if command == "PING":
            self._say("PONG")
        elif command == "INFO":
            self._say(f"INFO caudal-uno 1.0.0 s1={self.angles[1]} s2={self.angles[2]}")
        elif command == "D":
            self._say(f"D {self.distance_mm}")
        elif command.startswith("S"):
            number, angle = int(command[1]), int(command.split()[1])
            self._say(f"OK S{number} {angle}")
            if self.servo_answers:
                self.angles[number] = angle
                self._say(f"DONE S{number} {angle}")
        else:
            self._say("ERR comando desconocido")


class CountingClock:
    """Monotonic clock that advances on every read, so a silent port times out quickly."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 0.1
        return self.now


class StepClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _link(uno: FakeUno) -> SerialLink:
    link = SerialLink(uno, clock=CountingClock())
    link.wait_ready(1.0)
    return link


def test_the_link_reads_the_distance_and_reports_no_echo_as_none() -> None:
    uno = FakeUno()
    link = _link(uno)

    assert link.distance_mm() == WATER_MM
    uno.distance_mm = -1
    assert link.distance_mm() is None


def test_a_servo_move_is_reached_only_after_its_done_line() -> None:
    uno = FakeUno(servo_answers=False)
    link = _link(uno)

    link.move_servo(1, 90)

    assert uno.written[-1] == "S1 90"
    assert not link.reached(1, 90)


def test_info_reads_the_version_and_unknown_angles() -> None:
    info = _link(FakeUno()).info()

    assert info.version == "1.0.0"
    assert info.angles == (None, None)


def test_an_err_line_raises_and_silence_times_out() -> None:
    uno = FakeUno()
    link = _link(uno)
    with pytest.raises(SerialLinkError):
        link._exchange("XYZ", lambda text: text == "never")
    uno.write = lambda data, /: len(data)  # type: ignore[method-assign]
    with pytest.raises(SerialLinkError, match="no respondió"):
        link.ping()


def test_the_angle_must_be_valid() -> None:
    with pytest.raises(ValueError, match="180"):
        _link(FakeUno()).move_servo(1, 200)


def test_the_level_is_bounded_to_the_calibrated_range() -> None:
    sensor = UsbSensorSpec(empty_distance_mm=EMPTY_MM, full_distance_mm=FULL_MM, blind_zone_mm=30)

    assert sensor.level_m(WATER_MM) == pytest.approx(LEVEL_AT_WATER_M)
    assert sensor.level_m(EMPTY_MM + 20) == 0.0
    assert sensor.level_m(FULL_MM - 20) == pytest.approx(sensor.max_level_m)


def test_full_water_inside_the_blind_zone_is_rejected() -> None:
    with pytest.raises(ValueError, match="zona ciega"):
        UsbSensorSpec(empty_distance_mm=EMPTY_MM, full_distance_mm=20, blind_zone_mm=30)


def test_the_calibration_survives_a_save_and_a_load(tmp_path: Path) -> None:
    spec = load_usb_spec(CONFIG)
    changed = spec.model_copy(
        update={"sensor": spec.sensor.model_copy(update={"empty_distance_mm": 400})}
    )
    target = tmp_path / "maqueta-usb.yaml"

    save_usb_spec(changed, target)

    assert load_usb_spec(target) == changed


def _device(setup: MaquetaSetup, uno: FakeUno, clock: StepClock) -> MaquetaDevice:
    http = httpx.Client(base_url=BASE_URL, transport=setup.api.transport())
    return build_usb_maqueta_device(
        load_usb_spec(CONFIG), setup.identities, http, _link(uno), clock=clock, sleeper=clock.sleep
    )


def test_the_bridge_closes_both_servos_at_start() -> None:
    uno = FakeUno()
    _device(make_setup(), uno, StepClock(START))

    spec = load_usb_spec(CONFIG)
    assert uno.angles == {1: spec.servos[0].closed_deg, 2: spec.servos[1].closed_deg}


def test_the_measured_level_is_sent_as_signed_telemetry() -> None:
    setup = make_setup()
    clock = StepClock(START)
    device = _device(setup, FakeUno(), clock)

    device.run(seconds=load_usb_spec(CONFIG).timing.telemetry_interval_seconds)

    points = setup.api.telemetry[0]["points"]
    spec = load_usb_spec(CONFIG)
    assert {point["value"] for point in points} == {round(spec.sensor.level_m(WATER_MM), 2)}
    assert all(request.verified for request in setup.api.requests)


def test_an_open_command_moves_the_real_servo_and_is_acked() -> None:
    setup = make_setup()
    setup.api.commands[str(VALVE_1_DEVICE)] = [
        command_item(
            "0190f3a2-7777-7000-8000-000000000031",
            VALVE_1,
            "OPEN",
            START - timedelta(minutes=1),
            START + timedelta(minutes=30),
        )
    ]
    uno = FakeUno()
    device = _device(setup, uno, StepClock(START))

    device.run(seconds=OPEN_RUN_SECONDS)

    assert uno.angles[1] == load_usb_spec(CONFIG).servos[0].open_deg
    assert device.outlets[0].actuator.status is ValveStatus.OPEN
    assert setup.api.acks[-1]["payload"]["result"] == "ACKED"


def test_a_servo_that_never_answers_ends_in_fault() -> None:
    setup = make_setup()
    setup.api.commands[str(VALVE_1_DEVICE)] = [
        command_item(
            "0190f3a2-7777-7000-8000-000000000032",
            VALVE_1,
            "OPEN",
            START - timedelta(minutes=1),
            START + timedelta(minutes=30),
        )
    ]
    uno = FakeUno()
    device = _device(setup, uno, StepClock(START))
    uno.servo_answers = False

    device.run(seconds=load_usb_spec(CONFIG).valve.max_travel_seconds + OPEN_RUN_SECONDS)

    assert device.outlets[0].actuator.status is ValveStatus.FAULT


def test_a_reading_without_echo_sends_no_point_and_is_counted() -> None:
    setup = make_setup()
    uno = FakeUno(distance_mm=-1)
    device = _device(setup, uno, StepClock(START))

    report = device.run(seconds=load_usb_spec(CONFIG).timing.telemetry_interval_seconds)

    assert setup.api.telemetry == []
    assert report.missed_readings == load_usb_spec(CONFIG).timing.telemetry_interval_seconds
