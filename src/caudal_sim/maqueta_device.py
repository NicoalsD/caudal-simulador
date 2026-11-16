"""Virtual maqueta: a signed device that runs the tank model against the real API routes.

The maqueta is three signed identities, as the backend models them: the level sensor of the tank
(`LEVEL_SENSOR`, sends telemetry) and one actuator per outlet (`VALVE_ACTUATOR`, receives its
commands and confirms them). Each identity has its own Ed25519 key, so each one signs its own
requests.

Every tick, in this fixed order (the template method of the device):
1. The valves move towards their commanded position.
2. The tank advances one step with the openings the valves report.
3. The level becomes a LEVEL point of the telemetry batch.
4. When it is due, the batch is sent through the offline buffer (P11), so a lost network does not
   lose points. A 429 answer is retried later, not dropped.
5. When it is due, each valve polls its commands and runs them (`ValveCommandExecutor`).

The clock and the sleeper are injected, so the tests run without waiting and without a network.

@pattern P20 Template Method (`MaquetaDevice.tick`)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import sleep
from typing import Protocol
from uuid import UUID, uuid4

import httpx

from caudal_sim.actuator_driver import ActuatorDriver, SimulatedMotorDriver
from caudal_sim.event_bus import SimulationEventBus
from caudal_sim.live import LEVEL_DECIMALS, LEVEL_METRIC
from caudal_sim.maqueta_commands import HttpCommandSource
from caudal_sim.maqueta_plant import MaquetaPlantBuilder
from caudal_sim.maqueta_spec import (
    MaquetaBufferSpec,
    MaquetaSpec,
    MaquetaTimingSpec,
    MaquetaValveSpec,
)
from caudal_sim.offline_buffer import OfflineBufferTransport
from caudal_sim.telemetry_transport import (
    DeviceIdentity,
    SignedHttpTransport,
    TelemetryRequest,
    TelemetryTransport,
    TransportRejectedError,
    TransportUnavailableError,
    telemetry_request,
)
from caudal_sim.valve_actuator import ValveActuator
from caudal_sim.valve_command_executor import ValveCommandExecutor
from caudal_sim.valve_state import ValveStatus

MAX_POINTS_PER_BATCH = 100
RATE_LIMITED_CODE = "RATE_LIMITED"


class LevelStep(Protocol):
    """What one step of the tank gives the device: the level, in meters."""

    @property
    def level_m(self) -> float: ...


class TankSource(Protocol):
    """Where the level comes from: the tank model of the virtual maqueta or the real sensor."""

    def advance(self, seconds: float, openings: tuple[float, ...]) -> LevelStep: ...


class DeviceSpec(Protocol):
    """The parameters the device loop needs, shared by the virtual and the USB maqueta."""

    @property
    def valve(self) -> MaquetaValveSpec: ...

    @property
    def timing(self) -> MaquetaTimingSpec: ...

    @property
    def buffer(self) -> MaquetaBufferSpec: ...


@dataclass
class MaquetaReport:
    """What the run did. Counters only, so a long run keeps a small memory."""

    ticks: int = 0
    batches_sent: int = 0
    batches_queued: int = 0
    network_errors: int = 0
    last_level_m: float = 0.0
    last_error: str = ""


class RateLimitRetry(TelemetryTransport):
    """Adapter that turns a 429 into "retry later", so the buffer keeps the batch.

    @pattern P06 Adapter
    """

    def __init__(self, subject: TelemetryTransport) -> None:
        self._subject = subject

    def send(self, request: TelemetryRequest) -> None:
        try:
            self._subject.send(request)
        except TransportRejectedError as error:
            if error.code == RATE_LIMITED_CODE:
                raise TransportUnavailableError("La API limitó las peticiones (429).") from error
            raise


@dataclass(frozen=True)
class OutletChannel:
    """One outlet: its valve, its actuator and the executor that runs the valve's commands."""

    valve_id: UUID
    actuator: ValveActuator
    executor: ValveCommandExecutor
    source: HttpCommandSource


@dataclass(frozen=True)
class MaquetaIdentities:
    """Signed identities of the maqueta: the level sensor and one actuator per outlet."""

    sensor: DeviceIdentity
    outlets: tuple[tuple[DeviceIdentity, UUID], ...]


@dataclass
class MaquetaDevice:
    """Runs the maqueta. Use `build_maqueta_device` to wire it to the real HTTP client.

    @pattern P20 Template Method
    """

    plant: TankSource
    telemetry: OfflineBufferTransport
    outlets: tuple[OutletChannel, ...]
    spec: DeviceSpec
    clock: Callable[[], datetime]
    sleeper: Callable[[float], None]
    point_id_factory: Callable[[], UUID] = uuid4
    report: MaquetaReport = field(default_factory=MaquetaReport)
    _pending_points: list[dict[str, object]] = field(default_factory=list, init=False)
    _since_telemetry: float = field(default=0.0, init=False)
    _since_poll: float = field(default=0.0, init=False)

    def run(self, seconds: float | None = None) -> MaquetaReport:
        """Runs ticks for `seconds` of device time (forever when None), then finishes the run."""
        tick = self.spec.timing.tick_seconds
        remaining = seconds
        while remaining is None or remaining > 0:
            self.tick()
            self.sleeper(tick)
            if remaining is not None:
                remaining -= tick
        return self.finish()

    def finish(self) -> MaquetaReport:
        """Sends the waiting points and retries the queued batches, so nothing is lost on exit."""
        self._send_pending_points()
        self.telemetry.drain()
        self.report.batches_queued = self.telemetry.pending
        return self.report

    def tick(self) -> None:
        """One cycle of the device. The order of the steps is part of the model."""
        now = self.clock()
        tick = self.spec.timing.tick_seconds
        self._move_valves(tick)
        step = self._advance_tank(tick)
        self._record_level(now, step)
        self._send_telemetry_if_due(tick)
        self._poll_commands_if_due(now, tick)
        self.report.ticks += 1

    def _move_valves(self, tick: float) -> None:
        for channel in self.outlets:
            channel.actuator.advance(timedelta(seconds=tick))

    def _advance_tank(self, tick: float) -> LevelStep:
        openings = tuple(
            _opening_of(channel.actuator, timedelta(seconds=self.spec.valve.travel_seconds))
            for channel in self.outlets
        )
        step = self.plant.advance(tick, openings)
        self.report.last_level_m = step.level_m
        return step

    def _record_level(self, now: datetime, step: LevelStep) -> None:
        self._pending_points.append(
            {
                "id": str(self.point_id_factory()),
                "metric": LEVEL_METRIC,
                "value": round(step.level_m, LEVEL_DECIMALS),
                "observed_at": now.isoformat(),
            }
        )

    def _send_telemetry_if_due(self, tick: float) -> None:
        self._since_telemetry += tick
        due = self._since_telemetry >= self.spec.timing.telemetry_interval_seconds
        if due or len(self._pending_points) >= MAX_POINTS_PER_BATCH:
            self._send_pending_points()

    def _send_pending_points(self) -> None:
        if not self._pending_points:
            return
        batch = self._pending_points[:MAX_POINTS_PER_BATCH]
        self._pending_points = self._pending_points[MAX_POINTS_PER_BATCH:]
        self._since_telemetry = 0.0
        try:
            self.telemetry.send(telemetry_request(batch))
        except TransportRejectedError as error:
            # Not retried: the API refused the batch for a reason a retry does not fix.
            self._count_error(error.code)
            return
        self.report.batches_queued = self.telemetry.pending
        if self.telemetry.pending == 0:
            self.report.batches_sent += 1

    def _poll_commands_if_due(self, now: datetime, tick: float) -> None:
        self._since_poll += tick
        if self._since_poll < self.spec.timing.command_poll_seconds:
            return
        self._since_poll = 0.0
        for channel in self.outlets:
            try:
                channel.executor.poll(now)
            except (TransportUnavailableError, TransportRejectedError) as error:
                self._count_error(str(error))

    def _count_error(self, message: str) -> None:
        self.report.network_errors += 1
        self.report.last_error = message


def _opening_of(actuator: ValveActuator, travel: timedelta) -> float:
    """Opening between 0 and 1 that the valve reports. Travelling valves are linear in time.

    A FAULT valve counts as closed: the model does not know where the motor stopped, so it
    takes the conservative position. A reversal restarts the travel count, so the opening
    jumps there; this is a known approximation of the simple model.
    """
    state = actuator.capture()
    progress = min(1.0, state.travelled / travel)
    if state.status is ValveStatus.OPEN:
        return 1.0
    if state.status is ValveStatus.OPENING:
        return progress
    if state.status is ValveStatus.CLOSING:
        return 1.0 - progress
    return 0.0


def build_maqueta_device(  # noqa: PLR0913 - each parameter is one injected collaborator
    spec: MaquetaSpec,
    identities: MaquetaIdentities,
    http: httpx.Client,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleeper: Callable[[float], None] = sleep,
    point_id_factory: Callable[[], UUID] = uuid4,
    initial_level_m: float | None = None,
) -> MaquetaDevice:
    """Wires the maqueta to the HTTP client: one signed transport per identity."""
    if len(identities.outlets) != len(spec.outlets):
        raise ValueError("hace falta una identidad por salida")
    builder = MaquetaPlantBuilder(spec)
    if initial_level_m is not None:
        builder.with_initial_level(initial_level_m)
    plant = builder.build()
    return assemble_maqueta_device(
        plant,
        spec,
        identities,
        http,
        lambda _index: SimulatedMotorDriver(timedelta(seconds=spec.valve.travel_seconds)),
        clock=clock,
        sleeper=sleeper,
        point_id_factory=point_id_factory,
    )


def assemble_maqueta_device(  # noqa: PLR0913 - each parameter is one injected collaborator
    plant: TankSource,
    spec: DeviceSpec,
    identities: MaquetaIdentities,
    http: httpx.Client,
    driver_for: Callable[[int], ActuatorDriver],
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleeper: Callable[[float], None] = sleep,
    point_id_factory: Callable[[], UUID] = uuid4,
) -> MaquetaDevice:
    """Wires any tank source and motor drivers to the API: one signed transport per identity.

    `driver_for(index)` gives the motor driver of outlet `index` (0-based).
    """
    sensor_transport = SignedHttpTransport(http, identities.sensor)
    telemetry = OfflineBufferTransport(
        RateLimitRetry(sensor_transport),
        capacity=spec.buffer.capacity_batches,
        max_attempts=spec.buffer.max_attempts,
        sleeper=sleeper,
    )
    bus = SimulationEventBus()
    max_travel = timedelta(seconds=spec.valve.max_travel_seconds)
    channels: list[OutletChannel] = []
    for index, (identity, valve_id) in enumerate(identities.outlets):
        actuator = ValveActuator(driver_for(index), max_travel)
        source = HttpCommandSource(SignedHttpTransport(http, identity), valve_id, _parse_instant)
        executor = ValveCommandExecutor(valve_id, actuator, source, bus)
        channels.append(OutletChannel(valve_id, actuator, executor, source))
    return MaquetaDevice(
        plant=plant,
        telemetry=telemetry,
        outlets=tuple(channels),
        spec=spec,
        clock=clock,
        sleeper=sleeper,
        point_id_factory=point_id_factory,
    )


def _parse_instant(text: str) -> datetime:
    return datetime.fromisoformat(text)
