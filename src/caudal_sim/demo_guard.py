"""Check that the import target is the demo aqueduct before any historical data is sent.

The backend refuses imports outside the demo aqueduct with `403 DEMO_ONLY`, but the
simulator checks first so that it never sends a batch to a real aqueduct by mistake.
The public schedule states `aqueduct.is_demo`, which is the only public way to read it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from caudal_sim.api_client import ApiError, CaudalApiClient

HTTP_NOT_FOUND = 404
AQUEDUCT_KEY = "aqueduct"
IS_DEMO_KEY = "is_demo"
NOT_DEMO_MESSAGE = (
    "Importación cancelada: el acueducto destino no es el acueducto de demostración. "
    "Los datos simulados solo se importan al acueducto demo."
)
UNCONFIRMED_MESSAGE = (
    "Importación cancelada: no se pudo confirmar que el acueducto sea el de demostración. "
    "Revisa la URL de la API y el slug del acueducto demo."
)


class NonDemoTargetError(Exception):
    """The target is not the demo aqueduct, or the API could not confirm it. Nothing is sent."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DemoTargetGuard:
    """Refuses to import unless the public schedule of the target says `is_demo = true`."""

    def __init__(self, client: CaudalApiClient, slug: str) -> None:
        self._client = client
        self._slug = slug

    def ensure_demo(self) -> None:
        """Raises `NonDemoTargetError` unless the target aqueduct is the demo one."""
        try:
            schedule = self._client.get_public_schedule(self._slug)
        except ApiError as error:
            if error.status_code == HTTP_NOT_FOUND:
                raise NonDemoTargetError(UNCONFIRMED_MESSAGE) from error
            raise
        if _is_demo(schedule) is not True:
            raise NonDemoTargetError(NOT_DEMO_MESSAGE)


def _is_demo(schedule: Mapping[str, Any]) -> object:
    aqueduct = schedule.get(AQUEDUCT_KEY)
    if not isinstance(aqueduct, dict):
        return None
    return aqueduct.get(IS_DEMO_KEY)
