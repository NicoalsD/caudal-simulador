"""Modelos Pydantic de los escenarios YAML del simulador.

Cada escenario declara todos sus parámetros. Los campos extra se rechazan,
para que un error de escritura en el YAML no pase en silencio.
"""

from datetime import date
from typing import Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ScenarioError(ValueError):
    """Un escenario no se puede leer o no pasa la validación. El mensaje va en español."""


class ScenarioMeta(BaseModel):
    """Datos generales del escenario: nombre, zona horaria, fecha de inicio y semilla."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9-]*$", min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=300)
    timezone: str
    start_date: date
    simulated: Literal[True]
    default_seed: int = Field(ge=0)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as error:
            raise ValueError(f"zona horaria desconocida: {value}") from error
        return value


class TankSpec(BaseModel):
    """Tanque y regla pintada. El nivel del tanque se acota a esta regla."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    area_m2: float = Field(gt=0)
    gauge_min: float = Field(ge=0)
    gauge_max: float = Field(gt=0)
    gauge_step: float = Field(gt=0)
    initial_gauge: float = Field(ge=0)

    @model_validator(mode="after")
    def _gauge_rule_is_consistent(self) -> Self:
        if self.gauge_min >= self.gauge_max:
            raise ValueError("gauge_min debe ser menor que gauge_max")
        if self.gauge_step > self.gauge_max - self.gauge_min:
            raise ValueError("gauge_step no puede ser mayor que el rango de la regla")
        if not self.gauge_min <= self.initial_gauge <= self.gauge_max:
            raise ValueError("initial_gauge debe estar dentro de la regla")
        return self


MONTHS_PER_YEAR = 12


class MonthClimate(BaseModel):
    """Probabilidades de lluvia de un mes. Cada día húmedo o seco depende del día anterior."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    month: int = Field(ge=1, le=MONTHS_PER_YEAR)
    p_wet_after_dry: float = Field(ge=0, le=1)
    p_wet_after_wet: float = Field(ge=0, le=1)


class ClimateSpec(BaseModel):
    """Clima del escenario: una fila por mes, de enero (1) a diciembre (12)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    monthly: list[MonthClimate]

    @model_validator(mode="after")
    def _one_row_per_month(self) -> Self:
        months = sorted(row.month for row in self.monthly)
        if months != list(range(1, MONTHS_PER_YEAR + 1)):
            raise ValueError("climate.monthly debe tener exactamente una fila por mes (1 a 12)")
        return self


class Scenario(BaseModel):
    """Escenario completo validado. Es inmutable una vez construido."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meta: ScenarioMeta
    tank: TankSpec
    climate: ClimateSpec
