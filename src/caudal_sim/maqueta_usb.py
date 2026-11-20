"""Physical maqueta over USB: the Arduino UNO of `caudal-maqueta/uno` behind the same device loop.

The UNO has no network. This bridge runs on the computer it is plugged into: it reads the
HC-SR04 distance and moves the two servos through `SerialLink`, and it reuses `MaquetaDevice`
for everything else (signatures, telemetry, offline buffer, command polling and acks). So a
valve opened from the CAUDAL app moves the real servo, and the level the app shows is the
level measured in the bottle.

The calibration lives in a YAML file (`scenarios/maqueta-usb.yaml` by default):
- Sensor: the distance from the sensor to the bottom with the bottle empty and to the water
  with the bottle full. The level is `empty - measured`, bounded to `[0, empty - full]`.
- Servos: the angle that leaves the hose free (open) and the one that pinches it (closed).

@pattern P07 Bridge (`SerialServoDriver` is a real implementor of `ActuatorDriver`)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import sleep
from typing import Self
from uuid import UUID, uuid4

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from caudal_sim.actuator_driver import ActuatorDriver, MotorDirection
from caudal_sim.maqueta_device import (
    MaquetaDevice,
    MaquetaIdentities,
    assemble_maqueta_device,
)
from caudal_sim.maqueta_spec import (
    OUTLET_COUNT,
    MaquetaBufferSpec,
    MaquetaSpecError,
    MaquetaTimingSpec,
    MaquetaValveSpec,
)
from caudal_sim.serial_link import (
    MAX_ANGLE_DEG,
    MAX_SPIN_MS,
    MAX_SPIN_PULSE_US,
    MIN_ANGLE_DEG,
    MIN_SPIN_PULSE_US,
    SerialLink,
    SerialLinkError,
)

MILLIMETERS_PER_METER = 1000.0


class UsbSerialSpec(BaseModel):
    """USB serial port of the UNO."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    port: str = Field(min_length=1, description="Puerto, por ejemplo /dev/ttyACM0 o COM3.")
    baud: int = Field(gt=0)
    ready_timeout_seconds: float = Field(gt=0, description="Espera al READY tras el reinicio.")


class UsbSensorSpec(BaseModel):
    """Calibration of the HC-SR04 that looks down into the bottle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    empty_distance_mm: int = Field(gt=0, description="Sensor -> fondo, con la botella vacía.")
    full_distance_mm: int = Field(gt=0, description="Sensor -> agua, con la botella llena.")
    blind_zone_mm: int = Field(ge=0, description="Distancia mínima que el HC-SR04 mide bien.")

    @model_validator(mode="after")
    def _full_is_above_empty(self) -> Self:
        if self.full_distance_mm >= self.empty_distance_mm:
            raise ValueError("lleno debe quedar más cerca del sensor que vacío")
        if self.full_distance_mm < self.blind_zone_mm:
            raise ValueError("el agua llena queda dentro de la zona ciega del sensor; súbelo")
        return self

    @property
    def max_level_m(self) -> float:
        return (self.empty_distance_mm - self.full_distance_mm) / MILLIMETERS_PER_METER

    def level_m(self, distance_mm: int) -> float:
        """Water level for a measured distance, bounded to the calibrated range."""
        level = (self.empty_distance_mm - distance_mm) / MILLIMETERS_PER_METER
        return min(max(level, 0.0), self.max_level_m)


class UsbSpinSpec(BaseModel):
    """Timed turn of a continuous-rotation (360-degree) servo, which has no position: the pulse
    width sets speed and direction, and the time sets how far it turns. Each direction has its
    own time because the two speeds of a servo are rarely equal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    open_us: int = Field(ge=MIN_SPIN_PULSE_US, le=MAX_SPIN_PULSE_US, description="Pulso al abrir.")
    close_us: int = Field(
        ge=MIN_SPIN_PULSE_US, le=MAX_SPIN_PULSE_US, description="Pulso al cerrar."
    )
    open_ms: int = Field(ge=1, le=MAX_SPIN_MS, description="Tiempo de giro al abrir.")
    close_ms: int = Field(ge=1, le=MAX_SPIN_MS, description="Tiempo de giro al cerrar.")

    def pulse_and_time(self, direction: MotorDirection) -> tuple[int, int]:
        if direction is MotorDirection.OPEN:
            return self.open_us, self.open_ms
        return self.close_us, self.close_ms


class UsbServoSpec(BaseModel):
    """Calibration of one servo that pinches the hose of an outlet."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    open_deg: int = Field(ge=MIN_ANGLE_DEG, le=MAX_ANGLE_DEG, description="Manguera libre.")
    closed_deg: int = Field(ge=MIN_ANGLE_DEG, le=MAX_ANGLE_DEG, description="Manguera pisada.")
    spin: UsbSpinSpec | None = Field(
        default=None,
        description=(
            "Servo de rotación continua (360°): abre y cierra girando por tiempo. Con este "
            "bloque, open_deg y closed_deg no se usan."
        ),
    )
    hold_torque_after_move: bool = Field(
        default=True,
        description=(
            "Si es falso, el servo se suelta (R<n>) al llegar al ángulo, para que no siga "
            "empujando contra la manguera o el tope."
        ),
    )

    @model_validator(mode="after")
    def _angles_differ(self) -> Self:
        if self.open_deg == self.closed_deg:
            raise ValueError("el ángulo abierto y el cerrado deben ser distintos")
        return self

    def angle_for(self, direction: MotorDirection) -> int:
        return self.open_deg if direction is MotorDirection.OPEN else self.closed_deg


class UsbMaquetaSpec(BaseModel):
    """Complete USB maqueta file: port, calibration and the timing of the device loop."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    serial: UsbSerialSpec
    sensor: UsbSensorSpec
    servos: tuple[UsbServoSpec, ...] = Field(min_length=OUTLET_COUNT, max_length=OUTLET_COUNT)
    valve: MaquetaValveSpec
    timing: MaquetaTimingSpec
    buffer: MaquetaBufferSpec

    @model_validator(mode="after")
    def _spins_fit_the_travel(self) -> Self:
        limit_ms = self.valve.max_travel_seconds * 1000
        for servo in self.servos:
            if servo.spin is not None and max(servo.spin.open_ms, servo.spin.close_ms) >= limit_ms:
                raise ValueError(
                    f"el giro de {servo.name} debe durar menos que valve.max_travel_seconds"
                )
        return self


def load_usb_spec(path: Path) -> UsbMaquetaSpec:
    """Reads and validates the USB maqueta file. Errors are in Spanish."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise MaquetaSpecError(f"No se pudo leer la configuración de la maqueta: {path}") from error
    except yaml.YAMLError as error:
        raise MaquetaSpecError(f"El archivo {path} no es YAML válido.") from error
    if not isinstance(data, dict):
        raise MaquetaSpecError(f"El archivo {path} debe contener un mapa de parámetros.")
    try:
        return UsbMaquetaSpec.model_validate(data)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise MaquetaSpecError(f"Configuración inválida en {location}: {first['msg']}") from error


def save_usb_spec(spec: UsbMaquetaSpec, path: Path) -> None:
    """Writes the calibration back, so the next run starts with it."""
    header = (
        "# Maqueta física por USB (Arduino UNO). La escribe `caudal-sim maqueta-usb calibrar`.\n"
        "# Distancias en milímetros, ángulos en grados, tiempos en segundos.\n"
    )
    body = yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    path.write_text(header + body, encoding="utf-8")


@dataclass(frozen=True)
class MeasuredLevel:
    """One measurement of the real tank. `level_m` is None when the ping got no echo."""

    level_m: float | None
    distance_mm: int | None


class SerialLevelSource:
    """Level of the real bottle. A ping without echo gives no level, never a made-up one:
    a misaimed sensor must not look like an empty tank to the backend and the autopilot."""

    def __init__(self, link: SerialLink, sensor: UsbSensorSpec) -> None:
        self._link = link
        self._sensor = sensor

    def advance(self, seconds: float, openings: tuple[float, ...]) -> MeasuredLevel:
        distance = self._link.distance_mm()
        if distance is None:
            return MeasuredLevel(None, None)
        return MeasuredLevel(self._sensor.level_m(distance), distance)


class SerialServoDriver(ActuatorDriver):
    """Moves one servo through the UNO. The `DONE` line of the UNO is the limit switch.

    A servo that never says `DONE` (cable out, brown-out) never reaches its limit, so the
    valve goes to FAULT after its maximum travel, as a stalled motor would.
    """

    def __init__(
        self, link: SerialLink, servo: int, calibration: UsbServoSpec, travel_time: timedelta
    ) -> None:
        self._link = link
        self._servo = servo
        self._calibration = calibration
        self._travel_time = travel_time
        self._target: int | None = None
        self._released = False
        self._spinning = False

    @property
    def travel_time(self) -> timedelta:
        return self._travel_time

    def start(self, direction: MotorDirection) -> None:
        spin = self._calibration.spin
        if spin is not None:
            pulse_us, duration_ms = spin.pulse_and_time(direction)
            try:
                self._link.spin_servo(self._servo, pulse_us, duration_ms)
                self._spinning = True
            except SerialLinkError:
                self._spinning = False
            return
        self._target = self._calibration.angle_for(direction)
        self._released = False
        try:
            self._link.move_servo(self._servo, self._target)
        except SerialLinkError:
            self._target = None

    def stop(self) -> None:
        # A servo holds its last angle by itself; there is no motor to cut.
        return

    def limit_reached_after(self, travelled: timedelta) -> bool:
        if self._calibration.spin is not None:
            return self._spinning and self._link.spin_finished(self._servo)
        reached = self._target is not None and self._link.reached(self._servo, self._target)
        if reached and not self._calibration.hold_torque_after_move and not self._released:
            self._released = _release_quietly(self._link, self._servo)
        return reached


def _release_quietly(link: SerialLink, servo: int) -> bool:
    """Lets a servo go after it reached its angle. A failed release only means it keeps
    holding, which is the safe side, so it is not an error of the command."""
    try:
        link.release_servo(servo)
    except SerialLinkError:
        return False
    return True


def _release_after_reaching(
    link: SerialLink,
    targets: dict[int, int],
    max_wait_seconds: float,
    sleeper: Callable[[float], None],
    poll_seconds: float,
) -> None:
    """At start-up, waits for each servo that should not hold torque to reach its closed angle
    and releases it, up to `max_wait_seconds`."""
    waited = 0.0
    pending = dict(targets)
    while pending and waited <= max_wait_seconds:
        try:
            link.ping()  # reading the answer also records the DONE lines that came before it
        except SerialLinkError:
            return
        for servo, angle in list(pending.items()):
            if link.reached(servo, angle):
                _release_quietly(link, servo)
                del pending[servo]
        if pending:
            sleeper(poll_seconds)
            waited += poll_seconds


def build_usb_maqueta_device(  # noqa: PLR0913 - each parameter is one injected collaborator
    spec: UsbMaquetaSpec,
    identities: MaquetaIdentities,
    http: httpx.Client,
    link: SerialLink,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleeper: Callable[[float], None] = sleep,
    point_id_factory: Callable[[], UUID] = uuid4,
) -> MaquetaDevice:
    """Wires the UNO to the API. Both servos go to their closed angle first, because every
    valve of the device loop starts CLOSED and the real hose has to match it."""
    if len(identities.outlets) != len(spec.servos):
        raise ValueError("hace falta una identidad por salida")
    travel = timedelta(seconds=spec.valve.travel_seconds)
    for number, servo in enumerate(spec.servos, start=1):
        # A 360-degree servo has no position to go back to: it is assumed closed as it stands.
        if servo.spin is None:
            link.move_servo(number, servo.closed_deg)
    loose = {
        number: servo.closed_deg
        for number, servo in enumerate(spec.servos, start=1)
        if servo.spin is None and not servo.hold_torque_after_move
    }
    _release_after_reaching(
        link, loose, spec.valve.max_travel_seconds, sleeper, spec.timing.tick_seconds
    )
    return assemble_maqueta_device(
        SerialLevelSource(link, spec.sensor),
        spec,
        identities,
        http,
        lambda index: SerialServoDriver(link, index + 1, spec.servos[index], travel),
        clock=clock,
        sleeper=sleeper,
        point_id_factory=point_id_factory,
    )
