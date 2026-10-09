"""Demo guard tests: an import only starts when the target is the demo aqueduct."""

import pytest
import respx

from caudal_sim.api_client import CaudalApiClient
from caudal_sim.demo_guard import DemoTargetGuard, NonDemoTargetError

BASE_URL = "http://api.test"
SLUG = "guaitarilla-demo"
SCHEDULE_URL = f"{BASE_URL}/api/v1/public/{SLUG}/schedule"
HTTP_NOT_FOUND = 404
TIMEOUT_SECONDS = 5.0


def _schedule(is_demo: object) -> dict[str, object]:
    return {
        "aqueduct": {"name": "Acueducto de prueba", "is_demo": is_demo},
        "service_date": "2026-10-09",
        "items": [],
    }


def _guard() -> DemoTargetGuard:
    client = CaudalApiClient(BASE_URL, timeout_seconds=TIMEOUT_SECONDS)
    return DemoTargetGuard(client, SLUG)


def test_demo_aqueduct_passes_the_guard() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"/api/v1/public/{SLUG}/schedule").respond(200, json=_schedule(True))

        _guard().ensure_demo()


def test_real_aqueduct_is_refused_with_a_spanish_message() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"/api/v1/public/{SLUG}/schedule").respond(200, json=_schedule(False))

        with pytest.raises(NonDemoTargetError) as caught:
            _guard().ensure_demo()

    assert "no es el acueducto de demostración" in caught.value.message


@pytest.mark.parametrize("payload", [{"items": []}, {"aqueduct": "x"}, _schedule(None)])
def test_missing_or_malformed_demo_flag_is_refused(payload: dict[str, object]) -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"/api/v1/public/{SLUG}/schedule").respond(200, json=payload)

        with pytest.raises(NonDemoTargetError):
            _guard().ensure_demo()


def test_missing_public_schedule_is_refused_as_unconfirmed() -> None:
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"/api/v1/public/{SLUG}/schedule").respond(
            HTTP_NOT_FOUND,
            json={"error": {"code": "NOT_FOUND", "message": "No encontramos ese recurso."}},
        )

        with pytest.raises(NonDemoTargetError) as caught:
            _guard().ensure_demo()

    assert "no se pudo confirmar" in caught.value.message
