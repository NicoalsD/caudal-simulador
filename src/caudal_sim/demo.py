"""Demo mode: the scripted field faults that the system must handle, on the demo aqueduct.

The script runs on top of the live runner, so the same data reaches the API by the same doors.
The faults are the ones of `Datos-simulados.md`, section 6: a value outside the gauge rule, a
note of muddy water, a leak that a household reports, and a sensor that loses its signal.
The steps the simulator cannot drive (the AI service down, the board's decisions, the
publication and the minutes) are listed as manual steps, so nothing is reported as done when
it was not.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from caudal_sim.api_client import ApiError
from caudal_sim.api_payload import ID_LABEL
from caudal_sim.clock import HOURS_PER_DAY
from caudal_sim.dashboard_session import ControlAction, ControlRequest
from caudal_sim.live import SENSOR_SILENT_HOURS, LiveWiring
from caudal_sim.scenario import DemoSpec
from caudal_sim.terrain import SimulationRun

DEMO_LABEL = "demo"
DEMO_FORM_AGE_SECONDS = 10
NORMAL_APPEARANCE = "NORMAL"
LEAK_CATEGORY = "LEAK"
GAUGE_ERROR_CODE = "GAUGE_OUT_OF_RANGE"
GAUGE_ERROR_STATUS = 422
LEAK_DESCRIPTION = "Hay agua saliendo del tubo de la calle principal. Dato simulado."
LEAK_LOCATION = "Ubicación simulada"
MANUAL_NOTE = "Paso manual: el simulador no lo controla."
DECIMALS = 2


@dataclass(frozen=True)
class DemoCheck:
    """One line of the checklist. `passed` is None for a step that a person must do."""

    step: str
    expected: str
    observed: str
    passed: bool | None


MANUAL_CHECKS: tuple[DemoCheck, ...] = (
    DemoCheck(
        "IA caída",
        "El pronóstico cambia a la estimación simple con fallback_reason = CIRCUIT_OPEN.",
        "Paso manual: detener el servicio de IA y revisar el tablero del backend.",
        None,
    ),
    DemoCheck(
        "Propuesta y decisión",
        "La Junta aprueba con un cambio y motivo; la versión original queda guardada.",
        "Paso manual: lo decide una persona en el frontend de la Junta.",
        None,
    ),
    DemoCheck(
        "Publicación",
        "La página pública, el WhatsApp y el cartel muestran Datos simulados.",
        "Paso manual: publicar el horario en el frontend.",
        None,
    ),
    DemoCheck(
        "Cierre y acta",
        "El acta separa observado, estimado, inferido y confirmado.",
        "Paso manual: cerrar el día y generar el acta.",
        None,
    ),
)


class DemoDirector:
    """Runs the scripted faults at their hours and records what the API answered.

    `before_hour` is the hook of the live runner. Every fault goes through the same API calls
    as a real person or device would make, and the answer is kept for the checklist.
    """

    def __init__(
        self,
        spec: DemoSpec,
        wiring: LiveWiring,
        slug: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._spec = spec
        self._run = wiring.run
        self._api = wiring.api
        self._session = wiring.session
        self._tank_id = wiring.tank_id
        self._slug = slug
        self._now = now
        self._checks: list[DemoCheck] = []
        self._leak_report_hours = _leak_report_hours(self._run, spec.damage_report_hour_of_day)

    def before_hour(self, hour: int) -> None:
        """Runs the faults that are due at `hour`. Other hours pass untouched."""
        if hour == self._spec.gauge_error_hour:
            self._gauge_error(hour)
        if hour == self._spec.muddy_hour:
            self._muddy_water(hour)
        # One household report per reported leak, so two leaks reported together are two reports.
        for _ in range(self._leak_report_hours.count(hour)):
            self._leak_report(hour)
        if hour == self._spec.silent_sensor_hour:
            self._silent_sensor(hour)

    def checks(self) -> tuple[DemoCheck, ...]:
        """Automated checks in the order they ran, then the manual steps."""
        return (*self._checks, *MANUAL_CHECKS)

    def _at(self, hour: int) -> datetime:
        return self._run.start + timedelta(hours=hour)

    def _reading_id(self, kind: str, hour: int) -> UUID:
        return uuid5(self._tank_id, f"{ID_LABEL}:{DEMO_LABEL}:{kind}:{hour}")

    def _gauge_error(self, hour: int) -> None:
        wrong = {
            "id": str(self._reading_id("gauge-error", hour)),
            "tank_id": str(self._tank_id),
            "gauge_value": self._spec.gauge_error_value,
            "water_appearance_code": NORMAL_APPEARANCE,
            "damage_noticed": False,
            "note": "",
            "observed_at": self._at(hour).isoformat(),
        }
        try:
            self._api.post_reading(wrong)
        except ApiError as error:
            rejected = error.code == GAUGE_ERROR_CODE and error.status_code == GAUGE_ERROR_STATUS
            self._record(
                "Dato fuera de la regla",
                f"La API responde 422 {GAUGE_ERROR_CODE} y no guarda la lectura.",
                f"Respuesta {error.status_code} {error.code}.",
                rejected,
            )
        else:
            self._record(
                "Dato fuera de la regla",
                f"La API responde 422 {GAUGE_ERROR_CODE} y no guarda la lectura.",
                "La API aceptó el dato fuera de la regla.",
                False,
            )
        self._corrected_reading(hour)

    def _corrected_reading(self, hour: int) -> None:
        corrected = {
            "id": str(self._reading_id("gauge-corrected", hour)),
            "tank_id": str(self._tank_id),
            "gauge_value": round(self._level_at(hour), DECIMALS),
            "water_appearance_code": NORMAL_APPEARANCE,
            "damage_noticed": False,
            "note": "Corregida antes de reenviar.",
            "observed_at": self._at(hour).isoformat(),
        }
        self._post_reading_check("Lectura corregida", corrected)

    def _muddy_water(self, hour: int) -> None:
        body = {
            "id": str(self._reading_id("muddy", hour)),
            "tank_id": str(self._tank_id),
            "gauge_value": round(self._level_at(hour), DECIMALS),
            "water_appearance_code": self._spec.muddy_appearance_code,
            "damage_noticed": False,
            "note": self._spec.muddy_note,
            "observed_at": self._at(hour).isoformat(),
        }
        self._post_reading_check("Agua con barro", body)

    def _post_reading_check(self, step: str, body: dict[str, object]) -> None:
        try:
            self._api.post_reading(body)
        except ApiError as error:
            self._record(step, "La lectura se guarda (201).", f"Rechazada: {error.code}.", False)
            return
        self._record(step, "La lectura se guarda (201).", "Lectura guardada.", True)

    def _leak_report(self, hour: int) -> None:
        now = self._now()
        body = {
            "category_code": LEAK_CATEGORY,
            "description": LEAK_DESCRIPTION,
            "location_hint": LEAK_LOCATION,
            "website": "",
            "form_started_at": (now - timedelta(seconds=DEMO_FORM_AGE_SECONDS)).isoformat(),
        }
        try:
            answer = self._api.post_public_report(self._slug, body)
        except ApiError as error:
            self._record("Fuga reportada", "El reporte se registra (201).", error.code, False)
            return
        tracking = answer.get("tracking_code", "sin código")
        self._record(
            "Fuga reportada",
            "El reporte se registra con código de seguimiento (201).",
            f"Código de seguimiento {tracking}.",
            True,
        )

    def _silent_sensor(self, hour: int) -> None:
        self._session.request_control(ControlRequest(ControlAction.SENSOR_SILENT))
        self._record(
            "Sensor sin señal",
            "Los datos llegan con hora vieja y el tablero los marca como atrasados.",
            f"Sin señal durante {SENSOR_SILENT_HOURS} horas; "
            "luego se envía la telemetría guardada.",
            True,
        )

    def _level_at(self, hour: int) -> float:
        levels = self._run.truth.level_m_per_hour
        return float(levels[min(max(hour, 0), len(levels) - 1)])

    def _record(self, step: str, expected: str, observed: str, passed: bool) -> None:
        self._checks.append(DemoCheck(step, expected, observed, passed))


def _leak_report_hours(run: SimulationRun, hour_of_day: int) -> tuple[int, ...]:
    """Hour of each household report of the run, one entry per reported leak, in order."""
    horizon = run.days * HOURS_PER_DAY
    hours: list[int] = []
    for leak in run.truth.leaks:
        if leak.reported_day is None:
            continue
        hour = leak.reported_day * HOURS_PER_DAY + hour_of_day
        if hour < horizon:
            hours.append(hour)
    return tuple(sorted(hours))
