"""Datos de terreno: el motor horario y la separación entre lo observado y la verdad.

Lo observado es lo que llegaría al backend (lecturas, turnos y reportes de la comunidad).
La verdad de terreno (nivel real, demanda, fugas, rebose) nunca se envía al backend y se
guarda aparte.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt

from caudal_sim.climate import GammaRainfall, MonthlyMarkovClimate
from caudal_sim.clock import HOURS_PER_DAY, SimulationClock
from caudal_sim.demand import SectorDemandModel
from caudal_sim.leaks import Leak, LeakProcess
from caudal_sim.readings import (
    GaussianRoundingReadingModel,
    NoSignalDuplicateTransmission,
    TransmittedReading,
    take_readings,
)
from caudal_sim.scenario import Scenario
from caudal_sim.shifts import ShiftExecution, ShiftSimulator
from caudal_sim.source import LaggedRainSource
from caudal_sim.tank import Tank

DAMAGE_CATEGORY_LEAK = "FUGA"

STREAM_WET_DAYS = "clima.humedo"
STREAM_RAIN = "clima.lluvia"
STREAM_SHIFTS = "turnos"
STREAM_DEMAND = "demanda"
STREAM_LEAKS = "fugas"
STREAM_READINGS = "lecturas"
STREAM_TRANSMISSION = "transmision"


@dataclass(frozen=True)
class DamageReport:
    """Reporte de daño de una familia por el formulario público. No tiene datos personales."""

    report_id: int
    day_index: int
    category: str


@dataclass(frozen=True)
class ObservedData:
    """Lo que llegaría al backend por las puertas de la API."""

    readings: tuple[TransmittedReading, ...]
    shift_executions: tuple[ShiftExecution, ...]
    damage_reports: tuple[DamageReport, ...]


@dataclass(frozen=True)
class TruthData:
    """Verdad de terreno: lo que pasó de verdad. Nunca se envía al backend."""

    daily_rain_mm: npt.NDArray[np.float64]
    inflow_m3_per_hour: npt.NDArray[np.float64]
    muddy_water: npt.NDArray[np.bool_]
    requested_m3_per_hour: npt.NDArray[np.float64]
    delivered_m3_per_hour: npt.NDArray[np.float64]
    overflow_m3_per_hour: npt.NDArray[np.float64]
    level_m_per_hour: npt.NDArray[np.float64]
    leak_outflow_m3_per_hour: npt.NDArray[np.float64]
    leaks: tuple[Leak, ...]


@dataclass(frozen=True)
class SimulationRun:
    """Una corrida completa: metadatos, datos observados y verdad de terreno."""

    scenario_name: str
    seed: int
    days: int
    observed: ObservedData
    truth: TruthData


def run_simulation(scenario: Scenario, days: int, seed: int) -> SimulationRun:
    """Corre el gemelo digital durante `days` días con la semilla dada.

    Cada componente usa su propio flujo aleatorio con nombre, así que agregar un componente
    no cambia los datos de los demás. El reloj único se reconfigura al inicio de cada corrida.
    """
    clock = SimulationClock()
    start = datetime.combine(
        scenario.meta.start_date, time(0), tzinfo=ZoneInfo(scenario.meta.timezone)
    )
    clock.configure(start, seed)
    start_date = scenario.meta.start_date
    sector_ids = [sector.id for sector in scenario.sectors]

    wet = MonthlyMarkovClimate(scenario.climate.monthly).wet_days(
        start_date, days, clock.stream(STREAM_WET_DAYS)
    )
    daily_rain = GammaRainfall(scenario.climate.monthly).amounts_mm(
        wet, start_date, clock.stream(STREAM_RAIN)
    )
    source = LaggedRainSource(scenario.source).simulate(daily_rain)
    shifts = ShiftSimulator(scenario.schedule, sector_ids).simulate(
        days, clock.stream(STREAM_SHIFTS)
    )
    demand = SectorDemandModel(scenario.sectors, scenario.demand).hourly_demand_m3(
        days, clock.stream(STREAM_DEMAND)
    )
    leak_run = LeakProcess(scenario.leaks).simulate(days, clock.stream(STREAM_LEAKS))

    requested = leak_run.outflow_m3_per_hour.copy()
    for sector_id in sector_ids:
        requested += demand[sector_id] * shifts.valve_open[sector_id]

    tank = Tank(scenario.tank)
    hours = days * HOURS_PER_DAY
    delivered = np.zeros(hours)
    overflow = np.zeros(hours)
    level = np.zeros(hours)
    for hour in range(hours):
        step = tank.step(float(source.flow_m3_per_hour[hour]), float(requested[hour]))
        delivered[hour] = step.delivered_m3
        overflow[hour] = step.overflow_m3
        level[hour] = step.level_m

    model = GaussianRoundingReadingModel(scenario.tank, scenario.readings.noise_sd_m)
    readings = take_readings(
        level, days, scenario.readings.hours, model, clock.stream(STREAM_READINGS)
    )
    transmitted = NoSignalDuplicateTransmission(scenario.readings).transmit(
        readings, clock.stream(STREAM_TRANSMISSION)
    )
    reported_days = [day for leak in leak_run.leaks if (day := leak.reported_day) is not None]
    damage_reports = tuple(
        DamageReport(report_id=index, day_index=day, category=DAMAGE_CATEGORY_LEAK)
        for index, day in enumerate(reported_days)
    )

    return SimulationRun(
        scenario_name=scenario.meta.name,
        seed=seed,
        days=days,
        observed=ObservedData(
            readings=transmitted,
            shift_executions=shifts.executions,
            damage_reports=damage_reports,
        ),
        truth=TruthData(
            daily_rain_mm=daily_rain,
            inflow_m3_per_hour=source.flow_m3_per_hour,
            muddy_water=source.muddy_water,
            requested_m3_per_hour=requested,
            delivered_m3_per_hour=delivered,
            overflow_m3_per_hour=overflow,
            level_m_per_hour=level,
            leak_outflow_m3_per_hour=leak_run.outflow_m3_per_hour,
            leaks=leak_run.leaks,
        ),
    )
