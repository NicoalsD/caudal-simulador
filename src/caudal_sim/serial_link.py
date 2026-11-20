"""Line protocol with the Arduino UNO of the physical maqueta (`caudal-maqueta/uno`).

The UNO only measures the raw distance of its HC-SR04 and moves two servos to raw angles. This
link speaks its text protocol over USB serial (115200 baud, one line per message):

    PING        -> PONG
    INFO        -> INFO caudal-uno <version> s1=<deg> s2=<deg>
    D           -> D <mm>             (-1 when no echo came back)
    S<n> <deg>  -> OK S<n> <deg>      and later DONE S<n> <deg> when the servo gets there
    R<n>        -> OK R<n>
    T<n> <us> <ms> -> OK T<n> <us> <ms>  and later DONE T<n> (firmware 1.1.0, 360-degree servo)

Opening the port resets the UNO, so `open_serial_link` waits for its `READY` line. `DONE` lines
can arrive in the middle of another answer; the link records them and keeps reading.

@pattern P06 Adapter (`SerialLink` adapts the byte stream of the port to typed calls)
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

SERVO_COUNT = 2
MIN_ANGLE_DEG = 0
MAX_ANGLE_DEG = 180
MIN_SPIN_PULSE_US = 500
MAX_SPIN_PULSE_US = 2500
MAX_SPIN_MS = 10_000
NO_ECHO_MM = -1
DEFAULT_ANSWER_TIMEOUT_SECONDS = 2.0
READY_PREFIX = "READY"
ENCODING = "ascii"
TRACE_ENV = "CAUDAL_SIM_SERIAL_TRACE"


class SerialLinkError(RuntimeError):
    """The Arduino did not answer, answered with ERR or the port failed."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SerialPort(Protocol):
    """The part of `serial.Serial` the link uses, so the tests can inject a fake port."""

    def readline(self) -> bytes: ...

    def write(self, data: bytes, /) -> int | None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class DeviceInfo:
    """What `INFO` answers: firmware version and the last angle of each servo (None unknown)."""

    version: str
    angles: tuple[int | None, ...]


@dataclass
class SerialLink:
    """Typed calls over the UNO line protocol. Thread-safe: one exchange at a time."""

    port: SerialPort
    clock: Callable[[], float] = time.monotonic
    answer_timeout_seconds: float = DEFAULT_ANSWER_TIMEOUT_SECONDS
    _reached: dict[int, int] = field(default_factory=dict, init=False)
    _spun: set[int] = field(default_factory=set, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def wait_ready(self, timeout_seconds: float) -> str:
        """Waits for the `READY` line the UNO prints at boot, and returns it."""
        with self._lock:
            return self._read_until(lambda text: text.startswith(READY_PREFIX), timeout_seconds)

    def ping(self) -> None:
        self._exchange("PING", lambda text: text == "PONG")

    def info(self) -> DeviceInfo:
        answer = self._exchange("INFO", lambda text: text.startswith("INFO "))
        parts = answer.split()
        angles: list[int | None] = []
        for index in range(1, SERVO_COUNT + 1):
            value = _field(parts, f"s{index}")
            angles.append(None if value is None or value < 0 else value)
        version = parts[2] if len(parts) > 2 else ""  # noqa: PLR2004 - "INFO caudal-uno <v>"
        return DeviceInfo(version=version, angles=tuple(angles))

    def distance_mm(self) -> int | None:
        """Median distance from the sensor to the water, in millimeters. None without echo."""
        answer = self._exchange("D", lambda text: text.startswith("D "))
        try:
            value = int(answer.split()[1])
        except (IndexError, ValueError) as error:
            raise SerialLinkError(f"Respuesta de distancia inválida: {answer!r}") from error
        return None if value == NO_ECHO_MM else value

    def move_servo(self, servo: int, angle_deg: int) -> None:
        """Starts a smooth move of `servo` (1 or 2). `reached` tells when it got there."""
        _check_servo(servo)
        if not MIN_ANGLE_DEG <= angle_deg <= MAX_ANGLE_DEG:
            raise ValueError("el ángulo del servo debe estar entre 0 y 180 grados")
        with self._lock:
            self._reached.pop(servo, None)
            self._send(f"S{servo} {angle_deg}")
            self._read_until(lambda text: text.startswith(f"OK S{servo} "))

    def spin_servo(self, servo: int, pulse_us: int, duration_ms: int) -> None:
        """Turns a continuous-rotation (360-degree) servo: pulses of `pulse_us` (speed and
        direction) for `duration_ms`. `spin_finished` tells when the UNO stopped it."""
        _check_servo(servo)
        if not MIN_SPIN_PULSE_US <= pulse_us <= MAX_SPIN_PULSE_US:
            raise ValueError("el pulso debe estar entre 500 y 2500 microsegundos")
        if not 1 <= duration_ms <= MAX_SPIN_MS:
            raise ValueError("el giro debe durar entre 1 y 10000 milisegundos")
        with self._lock:
            self._spun.discard(servo)
            self._send(f"T{servo} {pulse_us} {duration_ms}")
            self._read_until(lambda text: text.startswith(f"OK T{servo} "))

    def spin_finished(self, servo: int) -> bool:
        """Whether the UNO said `DONE T<n>` for `servo` since its last spin."""
        return servo in self._spun

    def release_servo(self, servo: int) -> None:
        """Lets the servo go: it stops holding its position."""
        _check_servo(servo)
        self._exchange(f"R{servo}", lambda text: text == f"OK R{servo}")

    def reached(self, servo: int, angle_deg: int) -> bool:
        """Whether the UNO said `DONE` for `servo` at `angle_deg` since the last move."""
        return self._reached.get(servo) == angle_deg

    def close(self) -> None:
        self.port.close()

    def _exchange(self, command: str, matches: Callable[[str], bool]) -> str:
        with self._lock:
            self._send(command)
            return self._read_until(matches)

    def _send(self, command: str) -> None:
        try:
            self.port.write(f"{command}\n".encode(ENCODING))
        except OSError as error:
            raise SerialLinkError(f"No se pudo escribir en el puerto serie: {error}") from error

    def _read_until(
        self, matches: Callable[[str], bool], timeout_seconds: float | None = None
    ) -> str:
        limit = self.answer_timeout_seconds if timeout_seconds is None else timeout_seconds
        deadline = self.clock() + limit
        while self.clock() < deadline:
            try:
                raw = self.port.readline()
            except OSError as error:
                raise SerialLinkError(f"No se pudo leer el puerto serie: {error}") from error
            text = raw.decode(ENCODING, errors="replace").strip()
            if not text:
                continue
            if text.startswith("ERR"):
                raise SerialLinkError(f"El Arduino respondió: {text}")
            self._record_done(text)
            if matches(text):
                return text
        raise SerialLinkError("El Arduino no respondió a tiempo. Revisa el cable y el puerto.")

    def _record_done(self, text: str) -> None:
        parts = text.split()
        if len(parts) == 2 and parts[0] == "DONE" and parts[1].startswith("T"):  # noqa: PLR2004
            try:
                self._spun.add(int(parts[1][1:]))
            except ValueError:
                return
            return
        if len(parts) == 3 and parts[0] == "DONE" and parts[1].startswith("S"):  # noqa: PLR2004
            try:
                self._reached[int(parts[1][1:])] = int(parts[2])
            except ValueError:
                return


def _field(parts: list[str], name: str) -> int | None:
    prefix = f"{name}="
    for part in parts:
        if part.startswith(prefix):
            try:
                return int(part[len(prefix) :])
            except ValueError:
                return None
    return None


def _check_servo(servo: int) -> None:
    if not 1 <= servo <= SERVO_COUNT:
        raise ValueError("el servo debe ser 1 o 2")


@dataclass
class TracingPort:
    """Wraps a port and appends every line sent (`>`) and received (`<`) to a file, with the
    time. Only for diagnosis on the bench; it never holds secrets, only the UNO protocol."""

    port: SerialPort
    path: str

    def readline(self) -> bytes:
        raw = self.port.readline()
        if raw:
            self._log("<", raw)
        return raw

    def write(self, data: bytes, /) -> int | None:
        self._log(">", data)
        return self.port.write(data)

    def close(self) -> None:
        self.port.close()

    def _log(self, direction: str, raw: bytes) -> None:
        text = raw.decode(ENCODING, errors="replace").strip()
        stamp = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
        with open(self.path, "a", encoding="utf-8") as trace:
            trace.write(f"{stamp} {direction} {text}\n")


def open_serial_link(
    port_name: str, baud: int, *, ready_timeout_seconds: float, read_timeout_seconds: float = 0.2
) -> SerialLink:
    """Opens the USB port and waits until the UNO has booted.

    Some boards do not reset when the port opens, so when no `READY` line comes the link
    still checks the board with a `PING`. With `CAUDAL_SIM_SERIAL_TRACE=<file>` every line of
    the protocol is appended to that file.
    """
    import serial  # type: ignore[import-untyped]  # noqa: PLC0415 - only hardware commands load it

    try:
        port = serial.Serial(port_name, baud, timeout=read_timeout_seconds)
    except serial.SerialException as error:
        raise SerialLinkError(
            f"No se pudo abrir {port_name}: {error}. ¿Está conectado el Arduino? En Linux, tu "
            "usuario debe estar en el grupo dialout."
        ) from error
    trace_path = os.environ.get(TRACE_ENV)
    link = SerialLink(TracingPort(port, trace_path) if trace_path else port)
    try:
        link.wait_ready(ready_timeout_seconds)
    except SerialLinkError:
        link.ping()
    return link


def list_serial_ports() -> list[tuple[str, str]]:
    """USB serial ports of this computer, with their description."""
    from serial.tools import list_ports  # type: ignore[import-untyped]  # noqa: PLC0415

    # Only USB ports: the built-in ttyS ports of a PC never hold the UNO.
    return [
        (port.device, port.description) for port in list_ports.comports() if port.vid is not None
    ]
