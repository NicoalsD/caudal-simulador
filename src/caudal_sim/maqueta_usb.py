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
from caudal_sim.serial_link import MAX_ANGLE_DEG, MIN_ANGLE_DEG, SerialLink, SerialLinkError

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


class UsbServoSpec(BaseModel):
    """Calibration of one servo that pinches the hose of an outlet."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    open_deg: int = Field(ge=MIN_ANGLE_DEG, le=MAX_ANGLE_DEG, description="Manguera libre.")
    closed_deg: int = Field(ge=MIN_ANGLE_DEG, le=MAX_ANGLE_DEG, description="Manguera pisada.")

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

    @property
    def travel_time(self) -> timedelta:
        return self._travel_time

    def start(self, direction: MotorDirection) -> None:
        self._target = self._calibration.angle_for(direction)
        try:
            self._link.move_servo(self._servo, self._target)
        except SerialLinkError:
            self._target = None

    def stop(self) -> None:
        # A servo holds its last angle by itself; there is no motor to cut.
        return

    def limit_reached_after(self, travelled: timedelta) -> bool:
        return self._target is not None and self._link.reached(self._servo, self._target)


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
        link.move_servo(number, servo.closed_deg)
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
