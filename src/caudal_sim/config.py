"""Settings of the simulator: credentials and API endpoints, read from the environment.

Secrets never live in YAML or in code. They come from environment variables or from a
`.env` file (see `.env.example`), and the private key is read from `keys/` by path.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PRIVATE_KEY_PATH = Path("keys") / "ed25519-private.pem"
ENV_PREFIX = "CAUDAL_SIM_"
ENV_FILE = ".env"
MIN_TIMEOUT_SECONDS = 1.0
DEFAULT_TIMEOUT_SECONDS = 10.0


class SimulatorSettings(BaseSettings):
    """Connection and identity of the simulated PROJECT_TEAM user and the demo aqueduct."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=ENV_FILE,
        extra="ignore",
    )

    api_base_url: str = Field(min_length=1, description="Base URL of caudal-backend.")
    api_username: str = Field(min_length=1, description="Username of the PROJECT_TEAM user.")
    api_password: SecretStr = Field(description="Password of the PROJECT_TEAM user.")
    demo_aqueduct_slug: str = Field(min_length=1, description="Public slug of the demo aqueduct.")
    aqueduct_id: UUID = Field(description="Identifier of the demo aqueduct.")
    tank_id: UUID = Field(description="Identifier of the demo aqueduct's tank.")
    private_key_path: Path = Field(
        default=DEFAULT_PRIVATE_KEY_PATH,
        description="Ed25519 private key in PEM, outside git (keys/ is ignored).",
    )
    http_timeout_seconds: float = Field(
        default=DEFAULT_TIMEOUT_SECONDS,
        ge=MIN_TIMEOUT_SECONDS,
        description="Timeout of each HTTP call to the API, in seconds.",
    )


DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8000
MIN_PORT = 1
MIN_HOURS = 1
MAX_PORT = 65535
DASHBOARD_ENV_PREFIX = "CAUDAL_SIM_DASHBOARD_"
DEFAULT_DASHBOARD_STATIC_DIR = Path("dashboard") / "dist"


class DashboardSettings(BaseSettings):
    """Where the local dashboard API listens. It needs no credentials.

    The default host is the loopback address, so the API is only reachable from this computer.
    Other addresses are allowed on purpose (for example, inside a container), and the CLI warns.
    """

    model_config = SettingsConfigDict(
        env_prefix=DASHBOARD_ENV_PREFIX,
        env_file=ENV_FILE,
        extra="ignore",
    )

    host: str = Field(default=DEFAULT_DASHBOARD_HOST, min_length=1)
    port: int = Field(default=DEFAULT_DASHBOARD_PORT, ge=MIN_PORT, le=MAX_PORT)
    static_dir: Path = Field(
        default=DEFAULT_DASHBOARD_STATIC_DIR,
        description="Built dashboard (dashboard/dist). Served by the API when it exists.",
    )


SIMULATION_SPEED_FACTORS = (1, 10, 60)
DEFAULT_SPEED_FACTOR = 1


LIVE_ENV_PREFIX = "CAUDAL_SIM_LIVE_"
DEFAULT_HOUR_SECONDS = 1.0


class LiveSettings(BaseSettings):
    """Identities and pacing of the live mode. Every secret comes from the environment.

    The operator logs in to send readings. The board user is only needed for `--auto-junta`.
    The device identifier signs the telemetry; its private key is read from `keys/`.
    """

    model_config = SettingsConfigDict(
        env_prefix=LIVE_ENV_PREFIX,
        env_file=ENV_FILE,
        extra="ignore",
    )

    operator_username: str = Field(min_length=1, description="Usuario OPERATOR que envía lecturas.")
    operator_password: SecretStr = Field(description="Contraseña del usuario OPERATOR.")
    board_username: str | None = Field(
        default=None, description="Usuario de la Junta, solo para --auto-junta."
    )
    board_password: SecretStr | None = Field(
        default=None, description="Contraseña del usuario de la Junta, solo para --auto-junta."
    )
    device_id: UUID = Field(description="Identificador del nodo de nivel simulado.")
    hour_seconds: float = Field(
        default=DEFAULT_HOUR_SECONDS,
        ge=0,
        description="Segundos reales por hora simulada a velocidad 1.",
    )


MAQUETA_ENV_PREFIX = "CAUDAL_SIM_MAQUETA_"
DEFAULT_MAQUETA_KEY_DIR = Path("keys")


class MaquetaSettings(BaseSettings):
    """Identities of the virtual maqueta: one signed sensor and one signed actuator per outlet.

    Each identity is a device already registered in the backend, with its own public key. Its
    private key lives in `keys/` (git-ignored) or in the path given here. Nothing is hardcoded.
    """

    model_config = SettingsConfigDict(
        env_prefix=MAQUETA_ENV_PREFIX,
        env_file=ENV_FILE,
        extra="ignore",
    )

    api_base_url: str = Field(min_length=1, description="URL base de caudal-backend.")
    http_timeout_seconds: float = Field(
        default=DEFAULT_TIMEOUT_SECONDS,
        ge=MIN_TIMEOUT_SECONDS,
        description="Tiempo máximo de cada petición a la API, en segundos.",
    )
    sensor_device_id: UUID = Field(description="Dispositivo LEVEL_SENSOR del tanque.")
    sensor_private_key_path: Path = Field(
        default=DEFAULT_MAQUETA_KEY_DIR / "maqueta-sensor.pem",
        description="Clave privada Ed25519 del sensor, fuera de git.",
    )
    valve_1_device_id: UUID = Field(description="Dispositivo VALVE_ACTUATOR de la salida 1.")
    valve_1_valve_id: UUID = Field(description="Válvula que mueve la salida 1.")
    valve_1_private_key_path: Path = Field(
        default=DEFAULT_MAQUETA_KEY_DIR / "maqueta-valve-1.pem",
        description="Clave privada Ed25519 del actuador de la salida 1, fuera de git.",
    )
    valve_2_device_id: UUID = Field(description="Dispositivo VALVE_ACTUATOR de la salida 2.")
    valve_2_valve_id: UUID = Field(description="Válvula que mueve la salida 2.")
    valve_2_private_key_path: Path = Field(
        default=DEFAULT_MAQUETA_KEY_DIR / "maqueta-valve-2.pem",
        description="Clave privada Ed25519 del actuador de la salida 2, fuera de git.",
    )
