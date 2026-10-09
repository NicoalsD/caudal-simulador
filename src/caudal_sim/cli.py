"""Interfaz de línea de comandos del simulador de CAUDAL (textos en español)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from caudal_sim import __version__
from caudal_sim.builder import ScenarioBuilder
from caudal_sim.export import FORMATS, Format, export_run
from caudal_sim.scenario import ScenarioError
from caudal_sim.terrain import run_simulation

SCENARIOS_DIR = Path("scenarios")
SCENARIO_SUFFIX = ".yaml"
DEFAULT_SCENARIO = "normal"
DEFAULT_DAYS = 365
MIN_DAYS = 1
DEFAULT_OUTPUT = Path("outputs")
EXIT_SCENARIO_ERROR = 1


class ExportChoice(StrEnum):
    """Formatos de salida que ofrece la CLI."""

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
    try:
        builder = ScenarioBuilder().from_yaml(_scenario_path(scenario))
        if seed is not None:
            builder = builder.override("meta.default_seed", seed)
        resolved = builder.build()
    except ScenarioError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=EXIT_SCENARIO_ERROR) from error

    run = run_simulation(resolved, days, resolved.meta.default_seed)
    manifest = export_run(run, out, FORMATS_BY_CHOICE[export_format])
    typer.echo(
        f"Datos simulados ({resolved.meta.name}, semilla {run.seed}, {days} días) "
        f"en {out}. Manifiesto: {manifest}"
    )


def _scenario_path(value: str) -> Path:
    candidate = Path(value)
    if candidate.is_file():
        return candidate
    if candidate.suffix:
        return candidate
    return SCENARIOS_DIR / f"{value}{SCENARIO_SUFFIX}"
