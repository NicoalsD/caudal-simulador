"""Pydantic models of the simulator's YAML scenarios.

Each scenario declares all its parameters. Extra fields are rejected,
so that a typo in the YAML does not pass silently.
"""

from datetime import date
from typing import Literal, Self
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from caudal_sim.clock import HOURS_PER_DAY


class ScenarioError(ValueError):
    """A scenario cannot be read or fails validation. The message is in Spanish."""


class ScenarioMeta(BaseModel):
    """General scenario data: name, time zone, start date and seed."""

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
    """Tank and gauge rule. The tank level is bounded to this rule."""

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
    """Rain of one month: wet-day probabilities and the gamma shape and scale (mm)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    month: int = Field(ge=1, le=MONTHS_PER_YEAR)
    p_wet_after_dry: float = Field(ge=0, le=1)
    p_wet_after_wet: float = Field(ge=0, le=1)
    gamma_shape: float = Field(gt=0)
    gamma_scale_mm: float = Field(gt=0)


class ClimateSpec(BaseModel):
    """Scenario climate: one row per month, from January (1) to December (12)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    monthly: list[MonthClimate]

    @model_validator(mode="after")
    def _one_row_per_month(self) -> Self:
        months = sorted(row.month for row in self.monthly)
        if months != list(range(1, MONTHS_PER_YEAR + 1)):
            raise ValueError("climate.monthly debe tener exactamente una fila por mes (1 a 12)")
        return self


class SourceSpec(BaseModel):
    """Source: base flow, rain response with lag and muddy-water threshold."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_flow_m3_per_hour: float = Field(ge=0)
    rain_gain_m3_per_hour_per_mm: float = Field(ge=0)
    response_lag_hours: float = Field(gt=0)
    muddy_rain_threshold_mm: float = Field(ge=0)
    muddy_duration_hours: int = Field(ge=1)


class SectorSpec(BaseModel):
    """Aqueduct sector: a group of households that share one valve."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$", min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    households: int = Field(ge=1)


class DemandSpec(BaseModel):
    """Water demand: allowance per person, people per household and hourly profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    liters_per_person_per_day: float = Field(gt=0)
    persons_min: int = Field(ge=1)
    persons_max: int = Field(ge=1)
    # Relative weights of each hour of the day (0 to 23). The code normalizes them to fractions.
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
    """Published shift: opens a sector's valve in a window of hours of the day."""

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
    """Published schedule and compliance probabilities of each shift."""

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


class LeakSpec(BaseModel):
    """Leaks: monthly Poisson rate, flow, repair time and community report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rate_per_month: float = Field(ge=0)
    flow_m3_per_hour: float = Field(gt=0)
    repair_days_min: int = Field(ge=1)
    repair_days_max: int = Field(ge=1)
    report_probability_per_day: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _repair_range_is_forward(self) -> Self:
        if self.repair_days_min > self.repair_days_max:
            raise ValueError("repair_days_min no puede ser mayor que repair_days_max")
        return self


class ReadingSpec(BaseModel):
    """Operator readings: hours of the day when the gauge is read and reading error."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hours: list[int] = Field(min_length=1, max_length=HOURS_PER_DAY)
    noise_sd_m: float = Field(ge=0)
    duplicate_probability: float = Field(ge=0, le=1)
    no_signal_probability: float = Field(ge=0, le=1)
    max_delay_hours: int = Field(ge=1)

    @model_validator(mode="after")
    def _hours_are_sorted_unique_and_in_the_day(self) -> Self:
        if any(not 0 <= hour < HOURS_PER_DAY for hour in self.hours):
            raise ValueError("cada hora de lectura debe estar entre 0 y 23")
        if self.hours != sorted(set(self.hours)):
            raise ValueError("las horas de lectura deben ser únicas y en orden creciente")
        return self


class Scenario(BaseModel):
    """Complete validated scenario. Immutable once built."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    meta: ScenarioMeta
    tank: TankSpec
    climate: ClimateSpec
    source: SourceSpec
    sectors: list[SectorSpec] = Field(min_length=1)
    demand: DemandSpec
    schedule: ScheduleSpec
    leaks: LeakSpec
    readings: ReadingSpec

    @model_validator(mode="after")
    def _sector_references_are_valid(self) -> Self:
        ids = [sector.id for sector in self.sectors]
        if len(ids) != len(set(ids)):
            raise ValueError("los identificadores de sector deben ser únicos")
        unknown = sorted({turn.sector for turn in self.schedule.turns} - set(ids))
        if unknown:
            raise ValueError(f"el horario usa sectores que no existen: {', '.join(unknown)}")
        return self
