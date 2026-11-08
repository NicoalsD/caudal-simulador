"""Mass model of the virtual maqueta: one tank, a feed pump with a float, and two outlets.

Each step (one second by default) solves the mass balance of the tank:

    dV/dt = Q_in - sum(Cd * A_outlet * opening * sqrt(2 * g * h)) - overflow

The inflow is the pump flow while the float allows it. Each outlet drains by an orifice whose
flow grows with the square root of the level, so the tank empties faster when it is full. The
overflow is the part of the water above the overflow height, which leaves through the rebose.
The balance itself is the `Tank` of the scenario engine, which bounds the volume at zero and at
the overflow height.

@pattern P04 Builder (`MaquetaPlantBuilder`)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Self

from caudal_sim.maqueta_spec import OUTLET_COUNT, MaquetaSpec
from caudal_sim.scenario import TankSpec
from caudal_sim.tank import Tank

GRAVITY_M_PER_S2 = 9.81
METERS_PER_INCH = 0.0254
LITERS_PER_CUBIC_METER = 1000.0
SECONDS_PER_MINUTE = 60.0
# The level is sent with two decimals, so the tank bookkeeping keeps the same resolution.
LEVEL_RESOLUTION_M = 0.01


@dataclass(frozen=True)
class PlantStep:
    """Result of one step. Volumes are in cubic meters, the level in meters."""

    level_m: float
    pump_on: bool
    inflow_m3: float
    delivered_m3: float
    overflow_m3: float


class FloatSwitch:
    """High float with hysteresis: cuts the pump at `high_m`, starts it again under `restart_m`."""

    def __init__(self, high_m: float, restart_m: float, *, pump_on: bool = True) -> None:
        if restart_m >= high_m:
            raise ValueError("el arranque de la bomba debe estar por debajo del flotador")
        self._high_m = high_m
        self._restart_m = restart_m
        self._pump_on = pump_on

    @property
    def pump_on(self) -> bool:
        return self._pump_on

    def update(self, level_m: float) -> bool:
        """Reads the level and says whether the pump runs now."""
        if self._pump_on and level_m >= self._high_m:
            self._pump_on = False
        elif not self._pump_on and level_m < self._restart_m:
            self._pump_on = True
        return self._pump_on


class Outlet:
    """Orifice of one outlet. Its flow is Cd * A * opening * sqrt(2 g h)."""

    def __init__(self, diameter_m: float, discharge_coefficient: float) -> None:
        if diameter_m <= 0:
            raise ValueError("el diámetro de la salida debe ser mayor que cero")
        if not 0 < discharge_coefficient <= 1:
            raise ValueError("el coeficiente de descarga debe estar entre 0 y 1")
        self._area_m2 = math.pi * diameter_m * diameter_m / 4
        self._discharge_coefficient = discharge_coefficient

    @property
    def area_m2(self) -> float:
        return self._area_m2

    def flow_m3_per_s(self, level_m: float, opening: float) -> float:
        """Outflow at a level and an opening between 0 (closed) and 1 (fully open)."""
        if not 0 <= opening <= 1:
            raise ValueError("la apertura debe estar entre 0 y 1")
        if level_m <= 0 or opening == 0:
            return 0.0
        velocity = math.sqrt(2 * GRAVITY_M_PER_S2 * level_m)
        return self._discharge_coefficient * self._area_m2 * opening * velocity


class MaquetaPlant:
    """Tank, pump, float and outlets together. The valves are given to it at each step."""

    def __init__(
        self,
        tank: Tank,
        float_switch: FloatSwitch,
        pump_flow_m3_per_s: float,
        outlets: tuple[Outlet, ...],
        area_m2: float,
    ) -> None:
        if len(outlets) != OUTLET_COUNT:
            raise ValueError("la maqueta tiene exactamente dos salidas")
        if pump_flow_m3_per_s <= 0:
            raise ValueError("el caudal de la bomba debe ser mayor que cero")
        self._tank = tank
        self._float = float_switch
        self._pump_flow = pump_flow_m3_per_s
        self._outlets = outlets
        self._area_m2 = area_m2

    @property
    def level_m(self) -> float:
        return self._tank.volume_m3 / self._area_m2

    @property
    def pump_on(self) -> bool:
        return self._float.pump_on

    def advance(self, seconds: float, openings: tuple[float, ...]) -> PlantStep:
        """Advances the tank by `seconds` with the given outlet openings (0 to 1 each)."""
        if seconds <= 0:
            raise ValueError("el paso debe durar más de cero segundos")
        if len(openings) != len(self._outlets):
            raise ValueError("hace falta una apertura por salida")
        level = self.level_m
        pump_on = self._float.update(level)
        inflow = self._pump_flow * seconds if pump_on else 0.0
        requested = sum(
            outlet.flow_m3_per_s(level, opening) * seconds
            for outlet, opening in zip(self._outlets, openings, strict=True)
        )
        step = self._tank.step(inflow, requested)
        return PlantStep(
            level_m=step.level_m,
            pump_on=pump_on,
            inflow_m3=inflow,
            delivered_m3=step.delivered_m3,
            overflow_m3=step.overflow_m3,
        )


@dataclass
class MaquetaPlantBuilder:
    """Builds a `MaquetaPlant` from its scenario, with optional overrides for tests.

    @pattern P04 Builder
    """

    spec: MaquetaSpec
    _initial_level_m: float | None = field(default=None, init=False)
    _pump_on: bool = field(default=True, init=False)

    def with_initial_level(self, level_m: float) -> Self:
        """Starts the tank at another level than the scenario (for example, at a full tank)."""
        self._initial_level_m = level_m
        return self

    def with_pump_on(self, pump_on: bool) -> Self:
        """Sets the pump state at the start, before the float reads the level."""
        self._pump_on = pump_on
        return self

    def build(self) -> MaquetaPlant:
        tank = self.spec.tank
        initial = tank.initial_level_m if self._initial_level_m is None else self._initial_level_m
        # The `Tank` of the scenario engine bounds the volume between zero and its gauge maximum.
        # That maximum is the overflow height, so anything above it leaves through the rebose.
        tank_spec = TankSpec(
            area_m2=tank.area_m2,
            gauge_min=0.0,
            gauge_max=tank.overflow_m,
            gauge_step=LEVEL_RESOLUTION_M,
            initial_gauge=initial,
        )
        outlets = tuple(
            Outlet(outlet.diameter_in * METERS_PER_INCH, outlet.discharge_coefficient)
            for outlet in self.spec.outlets
        )
        return MaquetaPlant(
            tank=Tank(tank_spec),
            float_switch=FloatSwitch(
                tank.float_high_m, tank.float_restart_m, pump_on=self._pump_on
            ),
            pump_flow_m3_per_s=self.spec.pump.flow_l_per_min
            / LITERS_PER_CUBIC_METER
            / SECONDS_PER_MINUTE,
            outlets=outlets,
            area_m2=tank.area_m2,
        )
