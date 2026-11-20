"""Scenario of the virtual maqueta: one tank, a level float switch, a pump and two outlets.

The file `scenarios/maqueta.yaml` holds every parameter of the model. The code has no business
values: it only checks that the file is consistent. The data the maqueta produces is SIMULATED.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

OUTLET_COUNT = 2


class MaquetaSpecError(ValueError):
    """The maqueta file is missing, is not YAML or breaks a rule of the model."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class MaquetaMeta(BaseModel):
    """Identification of the scenario. The maqueta data is always simulated."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    simulated: Literal[True]


class MaquetaTankSpec(BaseModel):
    """Tank geometry and float switch, in meters and square meters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    area_m2: float = Field(gt=0, description="Cross-section area of the tank.")
    height_m: float = Field(gt=0, description="Physical height of the tank.")
    overflow_m: float = Field(gt=0, description="Height of the overflow pipe (rebose).")
    initial_level_m: float = Field(ge=0, description="Level at the start of the run.")
    float_high_m: float = Field(gt=0, description="High float: it cuts the pump at this level.")
    float_restart_m: float = Field(
        ge=0, description="Level under which the pump starts again (hysteresis)."
    )

    @model_validator(mode="after")
    def _levels_are_consistent(self) -> Self:
        if self.overflow_m > self.height_m:
            raise ValueError("el rebose no puede estar por encima de la altura del tanque")
        if self.initial_level_m > self.overflow_m:
            raise ValueError("el nivel inicial no puede superar el rebose")
        if self.float_restart_m >= self.float_high_m:
            raise ValueError("el nivel de arranque de la bomba debe ser menor que el del flotador")
        return self


class MaquetaPumpSpec(BaseModel):
    """Feed pump with a constant flow while it runs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    flow_l_per_min: float = Field(gt=0)


class MaquetaOutletSpec(BaseModel):
    """One outlet at the bottom of the tank: a pipe with a discharge coefficient."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    diameter_in: float = Field(gt=0, description="Nominal pipe diameter, in inches.")
    discharge_coefficient: float = Field(gt=0, le=1)


class MaquetaValveSpec(BaseModel):
    """Travel time of the outlet valves, from one limit switch to the other."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    travel_seconds: float = Field(gt=0)
    max_travel_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def _max_travel_covers_travel(self) -> Self:
        if self.max_travel_seconds < self.travel_seconds:
            raise ValueError("el tiempo máximo de maniobra no puede ser menor que el recorrido")
        return self


class MaquetaTimingSpec(BaseModel):
    """How often the virtual device runs its cycle and talks to the API, in seconds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tick_seconds: float = Field(gt=0, le=10, description="Physics step and loop period.")
    telemetry_interval_seconds: float = Field(gt=0)
    command_poll_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def _intervals_cover_one_tick(self) -> Self:
        if self.telemetry_interval_seconds < self.tick_seconds:
            raise ValueError("la telemetría no puede ser más frecuente que el ciclo")
        if self.command_poll_seconds < self.tick_seconds:
            raise ValueError("la consulta de comandos no puede ser más frecuente que el ciclo")
        return self


class MaquetaBufferSpec(BaseModel):
    """Telemetry batches kept while the network is down, and the retry passes of each drain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capacity_batches: int = Field(ge=1, description="Batches the buffer can hold.")
    max_attempts: int = Field(ge=1, description="Passes of the retry loop before waiting.")


class MaquetaSpec(BaseModel):
    """Complete maqueta scenario. Immutable once loaded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meta: MaquetaMeta
    tank: MaquetaTankSpec
    pump: MaquetaPumpSpec
    outlets: tuple[MaquetaOutletSpec, ...] = Field(min_length=OUTLET_COUNT, max_length=OUTLET_COUNT)
    valve: MaquetaValveSpec
    timing: MaquetaTimingSpec
    buffer: MaquetaBufferSpec


def load_maqueta_spec(path: Path) -> MaquetaSpec:
    """Reads and validates a maqueta scenario. Errors are in Spanish and never show secrets."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise MaquetaSpecError(f"No se pudo leer el escenario de la maqueta: {path}") from error
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise MaquetaSpecError(f"El archivo {path} no es YAML válido.") from error
    if not isinstance(data, dict):
        raise MaquetaSpecError(f"El archivo {path} debe contener un mapa de parámetros.")
    try:
        return MaquetaSpec.model_validate(data)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise MaquetaSpecError(
            f"Escenario de la maqueta inválido en {location}: {first['msg']}"
        ) from error
