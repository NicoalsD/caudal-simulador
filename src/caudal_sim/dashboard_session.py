"""Session of the dashboard: the state the API reports and the bus that streams its events.

The session owns the latest known state of the simulation (tank level, sensor reading and the
position of each valve). It listens to the `SimulationEventBus`, so every valve change updates
the state the API reports. The simulation pushes the levels. The session holds no credentials
and no personal data.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from caudal_sim.config import DEFAULT_SPEED_FACTOR, SIMULATION_SPEED_FACTORS
from caudal_sim.event_bus import SimulationEvent, SimulationEventBus, SimulationEventKind


class ControlAction(StrEnum):
    """Field conditions that the dashboard can inject. Valves are not on the list on purpose:
    no valve moves without a shift approved by the Junta."""

    LEAK = "LEAK"
    HEAVY_RAIN = "HEAVY_RAIN"
    SENSOR_STUCK = "SENSOR_STUCK"
    SENSOR_SILENT = "SENSOR_SILENT"
    NETWORK_DOWN = "NETWORK_DOWN"
    NETWORK_UP = "NETWORK_UP"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    SET_SPEED = "SET_SPEED"


@dataclass(frozen=True)
class ControlRequest:
    """One manual control. `factor` is only used by `SET_SPEED`."""

    action: ControlAction
    factor: int | None = None

    def __post_init__(self) -> None:
        if self.action is ControlAction.SET_SPEED:
            if self.factor not in SIMULATION_SPEED_FACTORS:
                raise ValueError("la velocidad debe ser una de las opciones del tablero")
        elif self.factor is not None:
            raise ValueError("solo la velocidad admite un factor")


@dataclass(frozen=True)
class ValveView:
    """Position of one valve as the dashboard shows it."""

    valve_id: str
    label: str
    status: str


@dataclass(frozen=True)
class DashboardSnapshot:
    """What the dashboard shows at one instant. Every level is in meters."""

    scenario: str
    updated_at: datetime | None
    tank_level_m: float | None
    sensor_level_m: float | None
    gauge_min_m: float | None
    gauge_max_m: float | None
    paused: bool
    speed_factor: int
    valves: tuple[ValveView, ...]


class DashboardSession:
    """Latest state of the simulation, updated by the simulation and by the bus.

    The session subscribes itself to the bus as an observer of valve events.
    """

    def __init__(self, scenario: str, bus: SimulationEventBus | None = None) -> None:
        self._scenario = scenario
        self._bus = bus if bus is not None else SimulationEventBus()
        self._updated_at: datetime | None = None
        self._tank_level_m: float | None = None
        self._sensor_level_m: float | None = None
        self._gauge_min_m: float | None = None
        self._gauge_max_m: float | None = None
        self._valves: dict[str, ValveView] = {}
        self._controls: deque[ControlRequest] = deque()
        self._paused = False
        self._speed_factor = DEFAULT_SPEED_FACTOR
        self._bus.subscribe(self)

    @property
    def bus(self) -> SimulationEventBus:
        """The bus whose events update this session."""
        return self._bus

    def register_valve(self, valve_id: str, label: str) -> None:
        """Adds a valve to the dashboard, closed until the simulation says otherwise."""
        self._valves[valve_id] = ValveView(valve_id=valve_id, label=label, status="CLOSED")

    def set_gauge_rule(self, gauge_min_m: float, gauge_max_m: float) -> None:
        """Records the painted gauge of the tank, so that the dashboard can draw the level."""
        if gauge_min_m >= gauge_max_m:
            raise ValueError("la regla del tanque debe tener un mínimo menor que el máximo")
        self._gauge_min_m = gauge_min_m
        self._gauge_max_m = gauge_max_m

    def set_levels(self, at: datetime, tank_level_m: float, sensor_level_m: float | None) -> None:
        """Records the true tank level and the level that the sensor reports at `at`."""
        self._updated_at = at
        self._tank_level_m = tank_level_m
        self._sensor_level_m = sensor_level_m

    def request_control(self, request: ControlRequest) -> None:
        """Queues a manual control for the simulation loop. Pause and speed also apply at once."""
        if request.action is ControlAction.PAUSE:
            self._paused = True
        elif request.action is ControlAction.RESUME:
            self._paused = False
        elif request.action is ControlAction.SET_SPEED and request.factor is not None:
            self._speed_factor = request.factor
        self._controls.append(request)

    def drain_controls(self) -> tuple[ControlRequest, ...]:
        """Takes the queued controls, in the order they were requested. Each one is taken once."""
        taken = tuple(self._controls)
        self._controls.clear()
        return taken

    @property
    def paused(self) -> bool:
        """Whether the simulation clock is paused, as the dashboard last requested."""
        return self._paused

    @property
    def speed_factor(self) -> int:
        """Speed of the simulation clock, as the dashboard last requested."""
        return self._speed_factor

    def snapshot(self) -> DashboardSnapshot:
        """Copy of the current state, safe to read while the simulation keeps running."""
        return DashboardSnapshot(
            scenario=self._scenario,
            updated_at=self._updated_at,
            tank_level_m=self._tank_level_m,
            sensor_level_m=self._sensor_level_m,
            gauge_min_m=self._gauge_min_m,
            gauge_max_m=self._gauge_max_m,
            paused=self._paused,
            speed_factor=self._speed_factor,
            valves=tuple(self._valves.values()),
        )

    def on_event(self, event: SimulationEvent) -> None:
        """Observer hook: a valve state change updates that valve. Other events do not."""
        if event.kind is not SimulationEventKind.VALVE_STATE_CHANGED:
            return
        current = self._valves.get(event.subject_id)
        if current is None:
            return
        self._valves[event.subject_id] = replace(current, status=event.detail)
