"""Modelos Pydantic de los escenarios YAML del simulador.

Cada escenario declara todos sus parámetros. Los campos extra se rechazan,
para que un error de escritura en el YAML no pase en silencio.
"""

from datetime import date
from typing import Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from caudal_sim.clock import HOURS_PER_DAY


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
    """Lluvia de un mes: probabilidades de día húmedo y forma y escala de la gamma (mm)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    month: int = Field(ge=1, le=MONTHS_PER_YEAR)
    p_wet_after_dry: float = Field(ge=0, le=1)
    p_wet_after_wet: float = Field(ge=0, le=1)
    gamma_shape: float = Field(gt=0)
    gamma_scale_mm: float = Field(gt=0)


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


class SourceSpec(BaseModel):
    """Fuente: caudal base, respuesta a la lluvia con retardo y umbral de agua con barro."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_flow_m3_per_hour: float = Field(ge=0)
    rain_gain_m3_per_hour_per_mm: float = Field(ge=0)
    response_lag_hours: float = Field(gt=0)
    muddy_rain_threshold_mm: float = Field(ge=0)
    muddy_duration_hours: int = Field(ge=1)


class SectorSpec(BaseModel):
    """Sector del acueducto: un grupo de hogares que comparte una válvula."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$", min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    households: int = Field(ge=1)


class DemandSpec(BaseModel):
    """Demanda de agua: dotación por persona, personas por hogar y perfil horario."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    liters_per_person_per_day: float = Field(gt=0)
    persons_min: int = Field(ge=1)
    persons_max: int = Field(ge=1)
    # Pesos relativos de cada hora del día (0 a 23). El código los normaliza a fracciones.
    hourly_weights: list[float] = Field(min_length=HOURS_PER_DAY, max_length=HOURS_PER_DAY)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.persons_min > self.persons_max:
            raise ValueError("persons_min no puede ser mayor que persons_max")
        if any(weight < 0 for weight in self.hourly_weights) or sum(self.hourly_weights) <= 0:
            raise ValueError(
                "hourly_weights no puede tener valores negativos y debe sumar más de 0"
            )
        return self


PROBABILITY_SUM_TOLERANCE = 1e-9


class TurnSpec(BaseModel):
    """Turno publicado: abre la válvula de un sector en una ventana de horas del día."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sector: str = Field(pattern=r"^[a-z][a-z0-9-]*$", min_length=1, max_length=32)
    start_hour: int = Field(ge=0, le=HOURS_PER_DAY - 1)
    end_hour: int = Field(ge=1, le=HOURS_PER_DAY)

    @model_validator(mode="after")
    def _window_is_forward(self) -> Self:
        if self.start_hour >= self.end_hour:
            raise ValueError("start_hour debe ser menor que end_hour")
        return self


class ScheduleSpec(BaseModel):
    """Horario publicado y probabilidades de cumplimiento de cada turno."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    turns: list[TurnSpec] = Field(min_length=1)
    p_completed: float = Field(ge=0, le=1)
    p_partial: float = Field(ge=0, le=1)
    p_not_executed: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _probabilities_sum_to_one(self) -> Self:
        total = self.p_completed + self.p_partial + self.p_not_executed
        if abs(total - 1.0) > PROBABILITY_SUM_TOLERANCE:
            raise ValueError("p_completed, p_partial y p_not_executed deben sumar 1")
        return self


class Scenario(BaseModel):
    """Escenario completo validado. Es inmutable una vez construido."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meta: ScenarioMeta
    tank: TankSpec
    climate: ClimateSpec
    source: SourceSpec
    sectors: list[SectorSpec] = Field(min_length=1)
    demand: DemandSpec
    schedule: ScheduleSpec

    @model_validator(mode="after")
    def _sector_references_are_valid(self) -> Self:
        ids = [sector.id for sector in self.sectors]
        if len(ids) != len(set(ids)):
            raise ValueError("los identificadores de sector deben ser únicos")
        unknown = sorted({turn.sector for turn in self.schedule.turns} - set(ids))
        if unknown:
            raise ValueError(f"el horario usa sectores que no existen: {', '.join(unknown)}")
        return self
