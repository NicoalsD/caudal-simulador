"""Command-line interface of the CAUDAL simulator (user-facing texts in Spanish)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from caudal_sim import __version__
from caudal_sim.api_client import ApiError
from caudal_sim.backfill import ImportKind, ImportLimitError, run_backfill
from caudal_sim.builder import ScenarioBuilder
from caudal_sim.config import ENV_PREFIX, SimulatorSettings
from caudal_sim.demo_guard import NonDemoTargetError
from caudal_sim.export import FORMATS, Format, export_run
from caudal_sim.scenario import Scenario, ScenarioError
from caudal_sim.terrain import run_simulation

SCENARIOS_DIR = Path("scenarios")
SCENARIO_SUFFIX = ".yaml"
DEFAULT_SCENARIO = "normal-year"
DEFAULT_DAYS = 365
MIN_DAYS = 1
DEFAULT_OUTPUT = Path("outputs")
EXIT_SCENARIO_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_IMPORT_ERROR = 3
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
        summary = run_backfill(kind, resolved, run, settings, dry_run=dry_run)
    except NonDemoTargetError as error:
        typer.echo(f"Error: {error.message}", err=True)
        raise typer.Exit(code=EXIT_IMPORT_ERROR) from error
    except ApiError as error:
        typer.echo(f"Error de la API ({error.code}): {error.message}", err=True)
        raise typer.Exit(code=EXIT_IMPORT_ERROR) from error
    except ImportLimitError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=EXIT_IMPORT_ERROR) from error

    if summary.dry_run:
        typer.echo(
            f"Simulación ({kind.value}): {summary.rows_total} filas en {summary.batches} lotes "
            f"({summary.duplicates_skipped} duplicadas omitidas). No se envió nada."
        )
        return
    typer.echo(
        f"Importación ({kind.value}): {summary.rows_accepted} filas aceptadas, "
        f"{summary.rows_rejected} rechazadas, en {summary.batches} lotes."
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
