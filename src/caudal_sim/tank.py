"""Aqueduct tank: hourly mass balance, with overflow and bounded volume."""

from __future__ import annotations

from dataclasses import dataclass

from caudal_sim.scenario import TankSpec


@dataclass(frozen=True)
class TankStep:
    """Result of one hour of the mass balance. All volumes are in m³."""

    volume_m3: float
    delivered_m3: float
    overflow_m3: float
    level_m: float


class Tank:
    """Mass balance of a tank with a one-hour step.

    Each hour: `V_final = V + inflow - delivered - overflow`. The delivered water never
    exceeds what is available, so the volume never drops below zero. The excess above the
    capacity leaves as overflow, and the capacity is the area times the maximum gauge.
    """

    def __init__(self, spec: TankSpec) -> None:
        self._area_m2 = spec.area_m2
        self._capacity_m3 = spec.area_m2 * spec.gauge_max
        self._volume_m3 = spec.area_m2 * spec.initial_gauge

    @property
    def capacity_m3(self) -> float:
        """Maximum tank volume, in m³ (area times the maximum gauge)."""
        return self._capacity_m3

    @property
    def volume_m3(self) -> float:
        """Current tank volume, in m³."""
        return self._volume_m3

    def restore_volume(self, volume_m3: float) -> None:
        """Puts the tank back at a volume saved earlier (used when restoring a snapshot)."""
        if not 0 <= volume_m3 <= self._capacity_m3:
            raise ValueError("el volumen restaurado debe estar entre cero y la capacidad")
        self._volume_m3 = volume_m3

    def step(self, inflow_m3: float, requested_outflow_m3: float) -> TankStep:
        """Advances one hour. The requested outflow may be trimmed if there is not enough water."""
        if inflow_m3 < 0 or requested_outflow_m3 < 0:
            raise ValueError("entrada y salida pedida no pueden ser negativas")

        available = self._volume_m3 + inflow_m3
        delivered = min(requested_outflow_m3, available)
        before_overflow = available - delivered
        overflow = max(0.0, before_overflow - self._capacity_m3)

        self._volume_m3 = before_overflow - overflow
        return TankStep(
            volume_m3=self._volume_m3,
            delivered_m3=delivered,
            overflow_m3=overflow,
            level_m=self._volume_m3 / self._area_m2,
        )
