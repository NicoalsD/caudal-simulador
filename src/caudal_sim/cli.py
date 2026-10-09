"""Interfaz de línea de comandos del simulador de CAUDAL (textos en español)."""

import typer

from caudal_sim import __version__

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
