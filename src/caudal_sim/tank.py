"""Tanque del acueducto: balance de masa por hora, con rebose y volumen acotado."""

from __future__ import annotations

from dataclasses import dataclass

from caudal_sim.scenario import TankSpec


@dataclass(frozen=True)
class TankStep:
    """Resultado de una hora del balance de masa. Todos los volúmenes van en m³."""

    volume_m3: float
    delivered_m3: float
    overflow_m3: float
    level_m: float


class Tank:
    """Balance de masa de un tanque con paso de una hora.

    En cada hora: `V_final = V + entrada - entregado - rebose`. El agua entregada nunca
    supera lo que hay disponible, así que el volumen no baja de cero. El exceso sobre la
    capacidad sale por rebose, y la capacidad es el área por la regla máxima.
    """

    def __init__(self, spec: TankSpec) -> None:
        self._area_m2 = spec.area_m2
        self._capacity_m3 = spec.area_m2 * spec.gauge_max
        self._volume_m3 = spec.area_m2 * spec.initial_gauge

    @property
    def capacity_m3(self) -> float:
        """Volumen máximo del tanque, en m³ (área por regla máxima)."""
        return self._capacity_m3

    @property
    def volume_m3(self) -> float:
        """Volumen actual del tanque, en m³."""
        return self._volume_m3

    def step(self, inflow_m3: float, requested_outflow_m3: float) -> TankStep:
        """Avanza una hora. La salida pedida puede recortarse si no hay agua suficiente."""
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
