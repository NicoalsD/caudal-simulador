"""Local API of the simulator dashboard, built with FastAPI.

The Swagger documentation (`/docs`) is in Spanish. The API has no CORS middleware: the
dashboard is served from the same origin, so no other site can call it from a browser. The
responses carry simulated data only: no usernames, tokens, keys or personal data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from caudal_sim import __version__
from caudal_sim.dashboard_session import DashboardSession

API_TITLE = "API del tablero del simulador CAUDAL"
API_DESCRIPTION = (
    "API local del tablero del simulador. Expone el estado de la simulación en vivo. "
    "Todos los datos son **simulados**. Por defecto solo escucha en 127.0.0.1."
)
SIMULATED_NOTICE = "Datos simulados"
STATE_PATH = "/api/tablero/estado"
TAG_DASHBOARD = "Tablero"


class ValveOut(BaseModel):
    """Position of one valve in the simulation."""

    id: str = Field(description="Identificador de la válvula simulada.")
    label: str = Field(description="Nombre de la válvula para el tablero.")
    status: str = Field(description="Estado de la válvula: CLOSED, OPENING, OPEN, CLOSING o FAULT.")


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
    valves: list[ValveOut] = Field(description="Válvulas de la simulación y su estado.")


def create_dashboard_app(session: DashboardSession) -> FastAPI:
    """Builds the API over one dashboard session. The session is shared, not copied."""
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
            valves=[
                ValveOut(id=valve.valve_id, label=valve.label, status=valve.status)
                for valve in snapshot.valves
            ],
        )

    return app
