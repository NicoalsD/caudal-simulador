"""Pruebas de humo de la interfaz de línea de comandos."""

from typer.testing import CliRunner

from caudal_sim import __version__
from caudal_sim.cli import app

runner = CliRunner()


def test_version_command_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"caudal-sim {__version__}"


def test_help_describes_the_simulator_in_spanish() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Simulador de datos" in result.output
