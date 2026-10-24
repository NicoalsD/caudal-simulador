"""Local API of the simulator dashboard, built with FastAPI.

The Swagger documentation (`/docs`) is in Spanish. The API has no CORS middleware: the
dashboard is served from the same origin, so no other site can call it from a browser. The
responses carry simulated data only: no usernames, tokens, keys or personal data.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from caudal_sim import __version__
from caudal_sim.config import SIMULATION_SPEED_FACTORS
from caudal_sim.dashboard_events import MAX_STREAM_EVENTS, SSE_CONTENT_TYPE, stream_frames
from caudal_sim.dashboard_session import ControlAction, ControlRequest, DashboardSession

API_TITLE = "API del tablero del simulador CAUDAL"
API_DESCRIPTION = (
    "API local del tablero del simulador. Expone el estado de la simulación en vivo. "
    "Todos los datos son **simulados**. Por defecto solo escucha en 127.0.0.1."
)
SIMULATED_NOTICE = "Datos simulados"
STATE_PATH = "/api/tablero/estado"
HTTP_ACCEPTED = 202
HTTP_UNPROCESSABLE = 422
SERVER_STOP_TIMEOUT_SECONDS = 5.0
EVENTS_PATH = "/api/tablero/eventos"
CONTROLS_PATH = "/api/tablero/controles"
NO_CACHE_HEADER = {"Cache-Control": "no-cache"}
TAG_DASHBOARD = "Tablero"


class ValveOut(BaseModel):
    """Position of one valve in the simulation."""

    id: str = Field(description="Identificador de la válvula simulada.")
    label: str = Field(description="Nombre de la válvula para el tablero.")
    status: str = Field(description="Estado de la válvula: CLOSED, OPENING, OPEN, CLOSING o FAULT.")


class ControlIn(BaseModel):
    """A manual condition for the simulation. The dashboard cannot open or close valves."""

    model_config = ConfigDict(extra="forbid")

    action: ControlAction = Field(
        description=(
            "Condición a inyectar: LEAK (fuga en un sector), HEAVY_RAIN (lluvia fuerte), "
            "SENSOR_STUCK (sensor pegado), SENSOR_SILENT (sensor sin señal), NETWORK_DOWN "
            "(se corta la red), NETWORK_UP (vuelve la red), PAUSE, RESUME o SET_SPEED. "
            "Las válvulas no se mueven desde el tablero: solo la Junta aprueba turnos."
        ),
    )
    factor: int | None = Field(
        default=None,
        description="Solo con SET_SPEED: velocidad del reloj, 1, 10 o 60.",
    )

    @model_validator(mode="after")
    def _factor_matches_action(self) -> ControlIn:
        if self.action is ControlAction.SET_SPEED and self.factor not in SIMULATION_SPEED_FACTORS:
            raise ValueError("con SET_SPEED, factor debe ser 1, 10 o 60")
        if self.action is not ControlAction.SET_SPEED and self.factor is not None:
            raise ValueError("factor solo se usa con SET_SPEED")
        return self


class ControlOut(BaseModel):
    """A control that the simulation will apply at its next step."""

    action: ControlAction = Field(description="Condición aceptada.")
    factor: int | None = Field(default=None, description="Velocidad, si la condición la usa.")
    status: str = Field(default="QUEUED", description="Estado: QUEUED, en cola para aplicarse.")


class StateOut(BaseModel):
    """State of the simulation at one instant. Every value is simulated."""

    scenario: str = Field(description="Nombre del escenario que se simula.")
    simulated: Literal[True] = Field(
        default=True, description="Siempre verdadero: los datos son simulados."
    )
    notice: str = Field(default=SIMULATED_NOTICE, description="Aviso que muestra el tablero.")
    updated_at: datetime | None = Field(
        default=None, description="Instante simulado de la última actualización."
    )
    tank_level_m: float | None = Field(
        default=None, description="Nivel real del tanque simulado, en metros."
    )
    sensor_level_m: float | None = Field(
        default=None, description="Nivel que reporta el sensor simulado, en metros."
    )
    gauge_min_m: float | None = Field(
        default=None, description="Mínimo de la regla pintada del tanque, en metros."
    )
    gauge_max_m: float | None = Field(
        default=None, description="Máximo de la regla pintada del tanque, en metros."
    )
    paused: bool = Field(default=False, description="Si el reloj de la simulación está en pausa.")
    speed_factor: int = Field(default=1, description="Velocidad del reloj: 1, 10 o 60.")
    valves: list[ValveOut] = Field(description="Válvulas de la simulación y su estado.")


def create_dashboard_app(session: DashboardSession, static_dir: Path | None = None) -> FastAPI:
    """Builds the API over one dashboard session. The session is shared, not copied.

    When `static_dir` holds the built dashboard, it is served from the same origin, after the
    API routes, so `/api` always answers first.
    """
    app = FastAPI(
        title=API_TITLE,
        version=__version__,
        description=API_DESCRIPTION,
        docs_url="/docs",
        redoc_url=None,
        openapi_tags=[{"name": TAG_DASHBOARD, "description": "Estado y eventos del tablero."}],
    )

    @app.get(
        STATE_PATH,
        response_model=StateOut,
        tags=[TAG_DASHBOARD],
        summary="Estado actual de la simulación",
        description="Devuelve el nivel del tanque, el sensor y las válvulas en este instante.",
        responses={200: {"description": "Estado de la simulación."}},
    )
    def read_state() -> StateOut:
        snapshot = session.snapshot()
        return StateOut(
            scenario=snapshot.scenario,
            updated_at=snapshot.updated_at,
            tank_level_m=snapshot.tank_level_m,
            sensor_level_m=snapshot.sensor_level_m,
            gauge_min_m=snapshot.gauge_min_m,
            gauge_max_m=snapshot.gauge_max_m,
            paused=snapshot.paused,
            speed_factor=snapshot.speed_factor,
            valves=[
                ValveOut(id=valve.valve_id, label=valve.label, status=valve.status)
                for valve in snapshot.valves
            ],
        )

    @app.get(
        EVENTS_PATH,
        tags=[TAG_DASHBOARD],
        summary="Eventos en vivo (SSE)",
        description=(
            "Flujo `text/event-stream` con los eventos del bus de la simulación: cambios de "
            "válvula, comandos entregados y confirmados. Cada evento es un nombre SSE igual a "
            "su tipo. Si el cliente se queda atrás, llega un evento `DROPPED` con los eventos "
            "perdidos. `max_events` cierra el flujo después de esa cantidad (para pruebas)."
        ),
        responses={200: {"content": {SSE_CONTENT_TYPE: {}}, "description": "Flujo de eventos."}},
        response_class=StreamingResponse,
    )
    async def stream_events(
        request: Request,
        max_events: Annotated[
            int | None,
            Query(ge=1, le=MAX_STREAM_EVENTS, description="Cierra el flujo tras esta cantidad."),
        ] = None,
    ) -> StreamingResponse:
        frames = stream_frames(
            session.bus,
            is_disconnected=request.is_disconnected,
            max_events=max_events,
        )
        return StreamingResponse(frames, media_type=SSE_CONTENT_TYPE, headers=NO_CACHE_HEADER)

    @app.post(
        CONTROLS_PATH,
        response_model=ControlOut,
        status_code=HTTP_ACCEPTED,
        tags=[TAG_DASHBOARD],
        summary="Inyecta una condición manual en la simulación",
        description=(
            "Pone en cola una condición de campo (fuga, lluvia, sensor pegado o sin señal, red, "
            "pausa o velocidad). La simulación la aplica en su siguiente paso. No abre ni cierra "
            "válvulas: los turnos los aprueba la Junta."
        ),
        responses={
            HTTP_ACCEPTED: {"description": "Condición aceptada y en cola."},
            HTTP_UNPROCESSABLE: {"description": "Condición o velocidad no válidas."},
        },
    )
    def request_control(control: ControlIn) -> ControlOut:
        session.request_control(ControlRequest(action=control.action, factor=control.factor))
        return ControlOut(action=control.action, factor=control.factor)

    if static_dir is not None and static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="tablero")
    return app


class DashboardServer:
    """Runs the dashboard API in a background thread, next to the simulation that feeds it."""

    def __init__(self, app: FastAPI, *, host: str, port: int) -> None:
        self._server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=port, log_level="warning")
        )
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Starts serving. Returns at once; the requests are answered by the thread."""
        self._thread = threading.Thread(target=self._server.run, name="tablero", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Asks the server to stop and waits for its thread to finish."""
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=SERVER_STOP_TIMEOUT_SECONDS)
