"""Live mode: the simulated aqueduct runs hour by hour and sends its data through the API.

The run is computed once with the same engine as `generate`, so with the same seed and
scenario `live` and `generate` agree. Then the runner plays it back one simulated hour at a
time. Each hour it applies the manual controls of the dashboard, reads the level sensor, sends
the level as signed telemetry through the offline buffer, and sends the readings whose
time has come. The human board is not simulated here: the proposals wait for a person in the
frontend, unless `auto_junta` is on for a long run.

Identifiers are derived with UUID version 5 from the seed, so a retry sends the same
identifier and the backend treats it as a duplicate, never as a new reading.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid5

from caudal_sim.api_client import ApiError, CaudalApiClient
from caudal_sim.api_payload import ID_LABEL, ApiPayloadAdapter
from caudal_sim.clock import HOURS_PER_DAY, SimulationClock
from caudal_sim.dashboard_session import ControlAction, DashboardSession
from caudal_sim.device_kit import FieldKitFactory
from caudal_sim.event_bus import SimulationEvent, SimulationEventKind
from caudal_sim.offline_buffer import BufferFullError, OfflineBufferTransport
from caudal_sim.readings import TransmittedReading
from caudal_sim.scenario import Scenario
from caudal_sim.shifts import ShiftOutcome
from caudal_sim.telemetry_transport import (
    TelemetryRequest,
    TelemetryTransport,
    TransportUnavailableError,
    telemetry_request,
)
from caudal_sim.terrain import SimulationRun
from caudal_sim.valve_state import ValveStatus

ONE_HOUR = timedelta(hours=1)
LEVEL_METRIC = "LEVEL"
LEVEL_DECIMALS = 2
PAUSE_POLL_SECONDS = 0.5
AUTO_JUNTA_EVERY_HOURS = HOURS_PER_DAY
SENSOR_STUCK_HOURS = 3
SENSOR_SILENT_HOURS = 6
SENSOR_STREAM = "sensor.vivo"
LIVE_ID_LABEL = f"{ID_LABEL}:live"
# Server errors and lost connections are retried later. Any other answer is final.
SERVER_ERROR_FROM = 500
NO_CONNECTION_STATUS = 0
UNSUPPORTED_CONTROLS = frozenset({ControlAction.LEAK, ControlAction.HEAVY_RAIN})


class LiveAbortedError(Exception):
    """The live run cannot go on, for example because the telemetry buffer is full."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NetworkGate(TelemetryTransport):
    """Proxy that cuts the network on demand. The dashboard uses it for `NETWORK_DOWN`.

    @pattern P11 Proxy
    """

    def __init__(self, subject: TelemetryTransport) -> None:
        self._subject = subject
        self._online = True

    @property
    def online(self) -> bool:
        return self._online

    def set_online(self, online: bool) -> None:
        self._online = online

    def send(self, request: TelemetryRequest) -> None:
        if not self._online:
            raise TransportUnavailableError("La red está cortada en la simulación.")
        self._subject.send(request)


@dataclass
class LiveReport:
    """What the live run did. Messages are in Spanish; they are meant for the person."""

    hours: int = 0
    readings_sent: int = 0
    readings_rejected: int = 0
    approvals: int = 0
    unsupported_controls: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LiveOptions:
    """How the run is paced and how far it goes."""

    hour_seconds: float
    max_hours: int | None = None
    auto_junta: bool = False


@dataclass(frozen=True)
class LiveWiring:
    """Everything the runner talks to. Tests replace each part with a fake."""

    scenario: Scenario
    run: SimulationRun
    session: DashboardSession
    telemetry: OfflineBufferTransport
    gate: NetworkGate
    api: CaudalApiClient
    adapter: ApiPayloadAdapter
    device_id: UUID
    sleeper: Callable[[float], None]
    board: CaudalApiClient | None = None


class LiveRunner:
    """Plays one simulated run through the API, hour by hour.

    `wiring.api` is logged in as the operator; `wiring.board` is logged in as the board and is
    only used when `options.auto_junta` is on. The sleeper is injected, so tests never wait.
    """

    def __init__(self, wiring: LiveWiring, options: LiveOptions) -> None:
        if options.auto_junta and wiring.board is None:
            raise LiveAbortedError("Para --auto-junta hace falta iniciar sesión como la Junta.")
        scenario = wiring.scenario
        run = wiring.run
        session = wiring.session
        self._run = run
        self._session = session
        self._telemetry = wiring.telemetry
        self._gate = wiring.gate
        self._api = wiring.api
        self._adapter = wiring.adapter
        self._device_id = wiring.device_id
        self._options = options
        self._sleeper = wiring.sleeper
        self._board = wiring.board
        self._report = LiveReport()
        self._held: list[TelemetryRequest] = []
        self._pending: deque[TransmittedReading] = deque()
        self._readings_by_hour = _group_by_sent_hour(run.observed.readings)
        self._stuck_until: datetime | None = None
        self._frozen: float | None = None
        self._silent_until: datetime | None = None
        self._valve_open: dict[str, bool] = {}
        sensor_rng = SimulationClock().stream(SENSOR_STREAM)
        self._sensor = FieldKitFactory.from_spec(
            scenario.devices,
            tank_level=self._level_at,
            start=run.start,
            rng=sensor_rng,
        ).create_sensor()
        session.set_gauge_rule(scenario.tank.gauge_min, scenario.tank.gauge_max)
        for sector in scenario.sectors:
            session.register_valve(sector.id, sector.name)
            self._valve_open[sector.id] = False

    def run(self) -> LiveReport:
        """Plays the run and returns what happened. Stops early only on `LiveAbortedError`."""
        total = self._run.days * HOURS_PER_DAY
        hours = total if self._options.max_hours is None else min(total, self._options.max_hours)
        for hour in range(hours):
            self._wait_while_paused()
            self._apply_controls(hour)
            self._pace(hour)
            self._step(hour)
        self._finish()
        self._report.hours = hours
        return self._report

    def _instant(self, hour: int) -> datetime:
        return self._run.start + hour * ONE_HOUR

    def _level_at(self, at: datetime) -> float:
        levels = self._run.truth.level_m_per_hour
        index = int((at - self._run.start) / ONE_HOUR)
        return float(levels[min(max(index, 0), len(levels) - 1)])

    def _apply_controls(self, hour: int) -> None:
        for request in self._session.drain_controls():
            at = self._instant(hour)
            if request.action is ControlAction.NETWORK_DOWN:
                self._gate.set_online(False)
            elif request.action is ControlAction.NETWORK_UP:
                self._gate.set_online(True)
                self._flush_telemetry()
            elif request.action is ControlAction.SENSOR_STUCK:
                self._stuck_until = at + SENSOR_STUCK_HOURS * ONE_HOUR
            elif request.action is ControlAction.SENSOR_SILENT:
                self._silent_until = at + SENSOR_SILENT_HOURS * ONE_HOUR
            elif request.action in UNSUPPORTED_CONTROLS:
                self._report.unsupported_controls.append(str(request.action))

    def _wait_while_paused(self) -> None:
        # The pause flag changes when the dashboard asks for it. Queued controls are left in the
        # queue, so they are applied in order once the clock runs again.
        while self._session.paused:
            self._sleeper(PAUSE_POLL_SECONDS)

    def _pace(self, hour: int) -> None:
        if hour > 0 and self._options.hour_seconds > 0:
            self._sleeper(self._options.hour_seconds / self._session.speed_factor)

    def _step(self, hour: int) -> None:
        at = self._instant(hour)
        level = self._level_at(at)
        reading = self._read_sensor(at)
        self._session.set_levels(at, level, reading)
        self._publish_valve_changes(hour, at)
        self._send_level(at, reading)
        self._pending.extend(self._readings_by_hour.get(hour, ()))
        self._send_pending_readings()
        if self._options.auto_junta and hour % AUTO_JUNTA_EVERY_HOURS == 0:
            self._approve_pending_proposals()

    def _read_sensor(self, at: datetime) -> float:
        value = self._sensor.read(at)
        if self._stuck_until is not None and at < self._stuck_until:
            if self._frozen is None:
                self._frozen = value
            return self._frozen
        self._frozen = None
        return value

    def _send_level(self, at: datetime, value: float) -> None:
        point = {
            "id": str(self._point_id(at)),
            "metric": LEVEL_METRIC,
            "value": round(value, LEVEL_DECIMALS),
            "observed_at": at.isoformat(),
        }
        batch = telemetry_request([point])
        if self._silent_until is not None and at < self._silent_until:
            self._held.append(batch)
            return
        for held in self._held:
            self._send_telemetry(held)
        self._held.clear()
        self._send_telemetry(batch)

    def _send_telemetry(self, request: TelemetryRequest) -> None:
        try:
            self._telemetry.send(request)
        except BufferFullError as error:
            raise LiveAbortedError(
                "El buffer sin conexión está lleno. La simulación se detiene para no perder datos."
            ) from error

    def _flush_telemetry(self) -> None:
        self._telemetry.drain()

    def _send_pending_readings(self) -> None:
        while self._pending and self._gate.online:
            reading = self._pending[0]
            try:
                self._api.post_reading(self._adapter.reading_row(reading))
            except ApiError as error:
                if _is_retryable(error):
                    return
                self._pending.popleft()
                self._report.readings_rejected += 1
                self._report.messages.append(f"Lectura rechazada ({error.code}): {error.message}")
                continue
            self._pending.popleft()
            self._report.readings_sent += 1

    def _publish_valve_changes(self, hour: int, at: datetime) -> None:
        open_now = self._sectors_open_at(hour)
        for sector_id, is_open in open_now.items():
            if self._valve_open[sector_id] == is_open:
                continue
            self._valve_open[sector_id] = is_open
            status = ValveStatus.OPEN if is_open else ValveStatus.CLOSED
            self._session.bus.publish(
                SimulationEvent(
                    occurred_at=at,
                    kind=SimulationEventKind.VALVE_STATE_CHANGED,
                    subject_id=sector_id,
                    detail=str(status),
                )
            )

    def _sectors_open_at(self, hour: int) -> dict[str, bool]:
        open_now = dict.fromkeys(self._valve_open, False)
        for shift in self._run.observed.shift_executions:
            if shift.outcome is ShiftOutcome.NOT_EXECUTED:
                continue
            start = shift.day_index * HOURS_PER_DAY + shift.start_hour
            if start <= hour < start + shift.open_hours:
                open_now[shift.sector_id] = True
        return open_now

    def _approve_pending_proposals(self) -> None:
        if self._board is None:
            return
        for proposal in self._board.list_pending_proposals():
            proposal_id = str(proposal.get("id", ""))
            lock_version = proposal.get("lock_version")
            if not proposal_id or not isinstance(lock_version, int):
                continue
            try:
                self._board.approve_proposal(proposal_id, lock_version)
            except ApiError as error:
                self._report.messages.append(f"Aprobación no aplicada ({error.code}).")
                continue
            self._report.approvals += 1

    def _finish(self) -> None:
        self._flush_telemetry()
        self._send_pending_readings()

    def _point_id(self, at: datetime) -> UUID:
        return uuid5(
            self._device_id, f"{LIVE_ID_LABEL}:{self._run.seed}:{LEVEL_METRIC}:{at.isoformat()}"
        )


def _is_retryable(error: ApiError) -> bool:
    return error.status_code == NO_CONNECTION_STATUS or error.status_code >= SERVER_ERROR_FROM


def _group_by_sent_hour(
    readings: tuple[TransmittedReading, ...],
) -> dict[int, list[TransmittedReading]]:
    grouped: dict[int, list[TransmittedReading]] = {}
    for reading in readings:
        grouped.setdefault(reading.sent_hour_index, []).append(reading)
    return grouped
