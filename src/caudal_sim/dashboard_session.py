"""Session of the dashboard: the state the API reports and the bus that streams its events.

The session owns the latest known state of the simulation (tank level, sensor reading and the
position of each valve). It listens to the `SimulationEventBus`, so every valve change updates
the state the API reports. The simulation pushes the levels. The session holds no credentials
and no personal data.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from caudal_sim.event_bus import SimulationEvent, SimulationEventBus, SimulationEventKind


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

    def snapshot(self) -> DashboardSnapshot:
        """Copy of the current state, safe to read while the simulation keeps running."""
        return DashboardSnapshot(
            scenario=self._scenario,
            updated_at=self._updated_at,
            tank_level_m=self._tank_level_m,
            sensor_level_m=self._sensor_level_m,
            gauge_min_m=self._gauge_min_m,
            gauge_max_m=self._gauge_max_m,
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
