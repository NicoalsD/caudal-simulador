"""Command-line interface of the CAUDAL simulator (user-facing texts in Spanish)."""

from __future__ import annotations

import time
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import httpx
import typer
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr, ValidationError

from caudal_sim import __version__
from caudal_sim.api_client import ApiError, CaudalApiClient
from caudal_sim.api_payload import ApiPayloadAdapter, ImportContext
from caudal_sim.backfill import BackfillOptions, ImportKind, ImportLimitError, run_backfill
from caudal_sim.backtest import export_backtest_windows
from caudal_sim.builder import ScenarioBuilder
from caudal_sim.config import (
    DEFAULT_DASHBOARD_PORT,
    ENV_PREFIX,
    LIVE_ENV_PREFIX,
    MAX_PORT,
    MIN_HOURS,
    MIN_PORT,
    DashboardSettings,
    LiveSettings,
    SimulatorSettings,
)
from caudal_sim.dashboard_api import DashboardServer, create_dashboard_app
from caudal_sim.dashboard_session import DashboardSession
from caudal_sim.demo_guard import DemoTargetGuard, NonDemoTargetError
from caudal_sim.export import FORMATS, Format, export_run
from caudal_sim.live import LiveAbortedError, LiveOptions, LiveRunner, LiveWiring, NetworkGate
from caudal_sim.minutes_export import export_confirmed_executions
from caudal_sim.offline_buffer import OfflineBufferTransport
from caudal_sim.scenario import Scenario, ScenarioError
from caudal_sim.signing import SigningKeyError, load_private_key
from caudal_sim.telemetry_transport import DeviceIdentity, SignedHttpTransport
from caudal_sim.terrain import run_simulation

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
NO_SIMULATION_NAME = "sin simulación en curso"

SCENARIOS_DIR = Path("scenarios")
SCENARIO_SUFFIX = ".yaml"
DEFAULT_SCENARIO = "normal-year"
DEFAULT_DAYS = 365
MIN_DAYS = 1
DEFAULT_OUTPUT = Path("outputs")
EXIT_SCENARIO_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_IMPORT_ERROR = 3
EXIT_LIVE_ERROR = 4
DEFAULT_LIVE_DAYS = 1
DEFAULT_BACKFILL_DAYS = 90


class ExportChoice(StrEnum):
    """Output formats offered by the CLI."""

    CSV = "csv"
    PARQUET = "parquet"
    BOTH = "both"


FORMATS_BY_CHOICE: dict[ExportChoice, tuple[Format, ...]] = {
    ExportChoice.CSV: ("csv",),
    ExportChoice.PARQUET: ("parquet",),
    ExportChoice.BOTH: FORMATS,
}


app = typer.Typer(
    help="Simulador de datos del acueducto veredal de CAUDAL.",
    no_args_is_help=True,
)
backfill_app = typer.Typer(
    help="Importa historial simulado al acueducto demo (solo con el usuario PROJECT_TEAM).",
    no_args_is_help=True,
)
app.add_typer(backfill_app, name="backfill")


@app.callback()
def main() -> None:
    """Simulador de datos de CAUDAL. Todos los datos generados son simulados."""


@app.command()
def version() -> None:
    """Muestra la versión del simulador."""
    typer.echo(f"caudal-sim {__version__}")


@app.command()
def tablero(
    host: Annotated[
        str | None,
        typer.Option(help="Dirección donde escucha. Por defecto, la de CAUDAL_SIM_DASHBOARD_HOST."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(
            help=f"Puerto. Por defecto {DEFAULT_DASHBOARD_PORT}.", min=MIN_PORT, max=MAX_PORT
        ),
    ] = None,
) -> None:
    """Levanta la API local del tablero (Swagger en /docs). Escucha en este equipo por defecto."""
    settings = DashboardSettings()
    bind_host = host or settings.host
    bind_port = port or settings.port
    if bind_host not in LOOPBACK_HOSTS:
        typer.echo(
            f"Atención: el tablero escucha en {bind_host}, fuera de este equipo. "
            "Usa solo redes de confianza."
        )
    typer.echo(f"Tablero del simulador en http://{bind_host}:{bind_port} (Swagger en /docs).")
    session = DashboardSession(scenario=NO_SIMULATION_NAME)
    app_instance = create_dashboard_app(session, settings.static_dir)
    uvicorn.run(app_instance, host=bind_host, port=bind_port, log_level="warning")


@app.command()
def live(  # noqa: PLR0913 - each parameter is one option that Typer reads from the signature
    *,
    scenario: Annotated[
        str,
        typer.Option(help="Nombre del escenario (scenarios/<nombre>.yaml) o ruta a un archivo."),
    ] = DEFAULT_SCENARIO,
    days: Annotated[
        int,
        typer.Option(help="Días simulados a reproducir.", min=MIN_DAYS),
    ] = DEFAULT_LIVE_DAYS,
    seed: Annotated[
        int | None,
        typer.Option(help="Semilla. Por defecto, la del escenario."),
    ] = None,
    max_hours: Annotated[
        int | None,
        typer.Option(help="Detiene la corrida tras estas horas simuladas.", min=MIN_HOURS),
    ] = None,
    auto_junta: Annotated[
        bool,
        typer.Option(
            "--auto-junta",
            help="Aprueba las propuestas pendientes con la Junta simulada. Solo corridas largas.",
        ),
    ] = False,
    dashboard: Annotated[
        bool,
        typer.Option("--tablero/--sin-tablero", help="Levanta el tablero junto a la simulación."),
    ] = True,
) -> None:
    """Simula el acueducto en tiempo real y envía sus datos al acueducto demo por la API."""
    resolved = _resolve_scenario(scenario, seed)
    settings = _settings_or_exit()
    live_settings = _live_settings_or_exit()
    board_settings = _board_settings_or_exit(live_settings, auto_junta)
    key = _load_key_or_exit(settings.private_key_path)
    run = run_simulation(resolved, days, resolved.meta.default_seed)
    session = DashboardSession(scenario=resolved.meta.name)
    with CaudalApiClient(
        settings.api_base_url, timeout_seconds=settings.http_timeout_seconds
    ) as api:
        _guard_demo_or_exit(api, settings.demo_aqueduct_slug)
        _login_or_exit(api, live_settings.operator_username, live_settings.operator_password)
        board = _board_client_or_none(settings, board_settings)
        with httpx.Client(
            base_url=settings.api_base_url, timeout=settings.http_timeout_seconds
        ) as telemetry_http:
            signed = SignedHttpTransport(
                telemetry_http, DeviceIdentity(live_settings.device_id, key)
            )
            gate = NetworkGate(signed)
            telemetry = OfflineBufferTransport.from_spec(
                gate, resolved.devices.buffer, sleeper=time.sleep
            )
            adapter = ApiPayloadAdapter(
                ImportContext(
                    aqueduct_id=settings.aqueduct_id,
                    tank_id=settings.tank_id,
                    start=run.start,
                    sector_slugs=tuple(sector.id for sector in resolved.sectors),
                )
            )
            wiring = LiveWiring(
                scenario=resolved,
                run=run,
                session=session,
                telemetry=telemetry,
                gate=gate,
                api=api,
                adapter=adapter,
                device_id=live_settings.device_id,
                sleeper=time.sleep,
                board=board,
            )
            options = LiveOptions(
                hour_seconds=live_settings.hour_seconds,
                max_hours=max_hours,
                auto_junta=auto_junta,
            )
            _run_live(wiring, options, session, dashboard)
    if board is not None:
        board.close()


def _run_live(
    wiring: LiveWiring,
    options: LiveOptions,
    session: DashboardSession,
    dashboard: bool,
) -> None:
    server: DashboardServer | None = None
    if dashboard:
        dashboard_settings = DashboardSettings()
        server = DashboardServer(
            create_dashboard_app(session, dashboard_settings.static_dir),
            host=dashboard_settings.host,
            port=dashboard_settings.port,
        )
        server.start()
        typer.echo(
            f"Tablero en http://{dashboard_settings.host}:{dashboard_settings.port} "
            "(datos simulados)."
        )
    try:
        report = LiveRunner(wiring, options).run()
    except LiveAbortedError as error:
        typer.echo(f"Error: {error.message}", err=True)
        raise typer.Exit(code=EXIT_LIVE_ERROR) from error
    finally:
        if server is not None:
            server.stop()
    typer.echo(
        f"Simulación en vivo: {report.hours} horas, {report.readings_sent} lecturas enviadas, "
        f"{report.readings_rejected} rechazadas, {report.approvals} aprobaciones, "
        f"{wiring.telemetry.pending} lotes de telemetría pendientes."
    )
    for message in report.messages:
        typer.echo(message)
    if report.unsupported_controls:
        typer.echo(
            "Condiciones pedidas en el tablero que este motor todavía no aplica: "
            + ", ".join(report.unsupported_controls)
        )


def _live_settings_or_exit() -> LiveSettings:
    try:
        return LiveSettings()
    except ValidationError as error:
        names = sorted(
            {f"{LIVE_ENV_PREFIX}{str(item['loc'][0]).upper()}" for item in error.errors()}
        )
        typer.echo(
            "Error: faltan o son inválidas estas variables de entorno (revisa .env): "
            + ", ".join(names),
            err=True,
        )
        raise typer.Exit(code=EXIT_CONFIG_ERROR) from error


def _board_settings_or_exit(live_settings: LiveSettings, auto_junta: bool) -> LiveSettings | None:
    if not auto_junta:
        return None
    if live_settings.board_username is None or live_settings.board_password is None:
        typer.echo(
            "Error: --auto-junta necesita CAUDAL_SIM_LIVE_BOARD_USERNAME y "
            "CAUDAL_SIM_LIVE_BOARD_PASSWORD en .env.",
            err=True,
        )
        raise typer.Exit(code=EXIT_CONFIG_ERROR)
    return live_settings


def _board_client_or_none(
    settings: SimulatorSettings, board_settings: LiveSettings | None
) -> CaudalApiClient | None:
    if board_settings is None or board_settings.board_username is None:
        return None
    client = CaudalApiClient(settings.api_base_url, timeout_seconds=settings.http_timeout_seconds)
    if board_settings.board_password is None:
        raise typer.Exit(code=EXIT_CONFIG_ERROR)
    _login_or_exit(client, board_settings.board_username, board_settings.board_password)
    return client


def _guard_demo_or_exit(api: CaudalApiClient, slug: str) -> None:
    try:
        DemoTargetGuard(api, slug).ensure_demo()
    except NonDemoTargetError as error:
        typer.echo(f"Error: {error.message}", err=True)
        raise typer.Exit(code=EXIT_LIVE_ERROR) from error
    except ApiError as error:
        typer.echo(f"Error: {error.message}", err=True)
        raise typer.Exit(code=EXIT_LIVE_ERROR) from error


def _login_or_exit(api: CaudalApiClient, username: str, password: SecretStr) -> None:
    try:
        api.login(username, password)
    except ApiError as error:
        typer.echo(f"Error: no se pudo iniciar sesión en la API ({error.code}).", err=True)
        raise typer.Exit(code=EXIT_LIVE_ERROR) from error


def _load_key_or_exit(path: Path) -> Ed25519PrivateKey:
    try:
        return load_private_key(path)
    except SigningKeyError as error:
        typer.echo(f"Error: {error.message}", err=True)
        raise typer.Exit(code=EXIT_CONFIG_ERROR) from error


@app.command("export-actas")
def export_actas(
    scenario: Annotated[
        str,
        typer.Option(help="Nombre del escenario (scenarios/<nombre>.yaml) o ruta a un archivo."),
    ] = DEFAULT_SCENARIO,
    days: Annotated[
        int,
        typer.Option(help="Días a simular.", min=MIN_DAYS),
    ] = DEFAULT_DAYS,
    seed: Annotated[
        int | None,
        typer.Option(help="Semilla. Por defecto, la del escenario."),
    ] = None,
    out: Annotated[
        Path,
        typer.Option(help="Carpeta donde se escriben los archivos de actas."),
    ] = DEFAULT_OUTPUT,
    export_format: Annotated[
        ExportChoice,
        typer.Option("--format", help="Formato de los archivos: csv, parquet o both."),
    ] = ExportChoice.BOTH,
) -> None:
    """Exporta las ejecuciones de turnos confirmadas para las actas. Solo datos observados."""
    resolved = _resolve_scenario(scenario, seed)
    run = run_simulation(resolved, days, resolved.meta.default_seed)
    manifest = export_confirmed_executions(run, out, FORMATS_BY_CHOICE[export_format])
    typer.echo(f"Ejecuciones confirmadas ({days} días) en {out}. Manifiesto: {manifest}")


@app.command("export-backtest")
def export_backtest(
    scenario: Annotated[
        str,
        typer.Option(help="Nombre del escenario (scenarios/<nombre>.yaml) o ruta a un archivo."),
    ] = DEFAULT_SCENARIO,
    days: Annotated[
        int,
        typer.Option(help="Días a simular.", min=MIN_DAYS),
    ] = DEFAULT_DAYS,
    seed: Annotated[
        int | None,
        typer.Option(help="Semilla. Por defecto, la del escenario."),
    ] = None,
    out: Annotated[
        Path,
        typer.Option(help="Carpeta donde se escriben las ventanas del backtest."),
    ] = DEFAULT_OUTPUT,
    export_format: Annotated[
        ExportChoice,
        typer.Option("--format", help="Formato de los archivos: csv, parquet o both."),
    ] = ExportChoice.BOTH,
) -> None:
    """Exporta ventanas históricas para el backtest de la IA, en dos conjuntos separados."""
    resolved = _resolve_scenario(scenario, seed)
    run = run_simulation(resolved, days, resolved.meta.default_seed)
    inputs, targets = export_backtest_windows(run, out, FORMATS_BY_CHOICE[export_format])
    typer.echo(
        f"Ventanas del backtest en {out}. Entradas observadas: {inputs}. "
        f"Objetivos con verdad: {targets}"
    )


@app.command()
def generate(
    scenario: Annotated[
        str,
        typer.Option(
            help="Nombre del escenario (scenarios/<nombre>.yaml) o ruta a un archivo YAML."
        ),
    ] = DEFAULT_SCENARIO,
    days: Annotated[
        int,
        typer.Option(help="Cantidad de días a simular.", min=MIN_DAYS),
    ] = DEFAULT_DAYS,
    seed: Annotated[
        int | None,
        typer.Option(
            help="Semilla. Por defecto, la del escenario. La misma semilla da los mismos datos."
        ),
    ] = None,
    out: Annotated[
        Path,
        typer.Option(help="Carpeta donde se escriben los datos y el manifiesto."),
    ] = DEFAULT_OUTPUT,
    export_format: Annotated[
        ExportChoice,
        typer.Option("--format", help="Formato de los archivos: csv, parquet o both."),
    ] = ExportChoice.BOTH,
) -> None:
    """Genera datos simulados de un escenario. No se envía nada al backend."""
    resolved = _resolve_scenario(scenario, seed)
    run = run_simulation(resolved, days, resolved.meta.default_seed)
    manifest = export_run(run, out, FORMATS_BY_CHOICE[export_format])
    typer.echo(
        f"Datos simulados ({resolved.meta.name}, semilla {run.seed}, {days} días) "
        f"en {out}. Manifiesto: {manifest}"
    )


@backfill_app.command("readings")
def backfill_readings(
    scenario: Annotated[
        str,
        typer.Option(help="Nombre del escenario (scenarios/<nombre>.yaml) o ruta a un archivo."),
    ] = DEFAULT_SCENARIO,
    days: Annotated[
        int,
        typer.Option(help="Días de historial a importar.", min=MIN_DAYS),
    ] = DEFAULT_BACKFILL_DAYS,
    seed: Annotated[
        int | None,
        typer.Option(help="Semilla. Por defecto, la del escenario."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Cuenta los lotes sin contactar la API."),
    ] = False,
) -> None:
    """Importa lecturas simuladas al acueducto demo. Los lotes respetan los límites de la API."""
    _run_backfill(ImportKind.READINGS, scenario, days, seed, dry_run)


@backfill_app.command("shift-executions")
def backfill_shift_executions(
    scenario: Annotated[
        str,
        typer.Option(help="Nombre del escenario (scenarios/<nombre>.yaml) o ruta a un archivo."),
    ] = DEFAULT_SCENARIO,
    days: Annotated[
        int,
        typer.Option(help="Días de historial a importar.", min=MIN_DAYS),
    ] = DEFAULT_BACKFILL_DAYS,
    seed: Annotated[
        int | None,
        typer.Option(help="Semilla. Por defecto, la del escenario."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Cuenta los lotes sin contactar la API."),
    ] = False,
) -> None:
    """Importa ejecuciones de turnos simuladas al acueducto demo."""
    _run_backfill(ImportKind.SHIFT_EXECUTIONS, scenario, days, seed, dry_run)


@backfill_app.command("incidents")
def backfill_incidents(
    scenario: Annotated[
        str,
        typer.Option(help="Nombre del escenario (scenarios/<nombre>.yaml) o ruta a un archivo."),
    ] = DEFAULT_SCENARIO,
    days: Annotated[
        int,
        typer.Option(help="Días de historial a importar.", min=MIN_DAYS),
    ] = DEFAULT_BACKFILL_DAYS,
    seed: Annotated[
        int | None,
        typer.Option(help="Semilla. Por defecto, la del escenario."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Cuenta los lotes sin contactar la API."),
    ] = False,
) -> None:
    """Importa incidentes simulados (reportes de fuga de la comunidad) al acueducto demo."""
    _run_backfill(ImportKind.INCIDENTS, scenario, days, seed, dry_run)


def _run_backfill(
    kind: ImportKind, scenario: str, days: int, seed: int | None, dry_run: bool
) -> None:
    resolved = _resolve_scenario(scenario, seed)
    settings = _settings_or_exit()
    run = run_simulation(resolved, days, resolved.meta.default_seed)
    try:
        summary = run_backfill(kind, resolved, run, settings, BackfillOptions(dry_run=dry_run))
    except NonDemoTargetError as error:
        typer.echo(f"Error: {error.message}", err=True)
        raise typer.Exit(code=EXIT_IMPORT_ERROR) from error
    except ApiError as error:
        typer.echo(f"Error de la API ({error.code}): {error.message}", err=True)
        raise typer.Exit(code=EXIT_IMPORT_ERROR) from error
    except ImportLimitError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=EXIT_IMPORT_ERROR) from error
    except SigningKeyError as error:
        typer.echo(f"Error: {error.message}", err=True)
        raise typer.Exit(code=EXIT_IMPORT_ERROR) from error

    if summary.dry_run:
        typer.echo(
            f"Simulación ({kind.value}): {summary.rows_total} filas en {summary.batches} lotes "
            f"({summary.duplicates_skipped} duplicadas omitidas). No se envió nada."
        )
        return
    typer.echo(
        f"Importación ({kind.value}): {summary.rows_accepted} filas aceptadas, "
        f"{summary.rows_rejected} rechazadas, en {summary.batches} lotes. "
        f"Manifiesto firmado: {summary.manifest_path}"
    )


def _resolve_scenario(value: str, seed: int | None) -> Scenario:
    try:
        builder = ScenarioBuilder().from_yaml(_scenario_path(value))
        if seed is not None:
            builder = builder.override("meta.default_seed", seed)
        return builder.build()
    except ScenarioError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=EXIT_SCENARIO_ERROR) from error


def _settings_or_exit() -> SimulatorSettings:
    try:
        return SimulatorSettings()
    except ValidationError as error:
        names = sorted({f"{ENV_PREFIX}{str(item['loc'][0]).upper()}" for item in error.errors()})
        typer.echo(
            "Error: faltan o son inválidas estas variables de entorno (revisa .env): "
            + ", ".join(names),
            err=True,
        )
        raise typer.Exit(code=EXIT_CONFIG_ERROR) from error


def _scenario_path(value: str) -> Path:
    candidate = Path(value)
    if candidate.is_file():
        return candidate
    if candidate.suffix:
        return candidate
    return SCENARIOS_DIR / f"{value}{SCENARIO_SUFFIX}"
