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
MAX_PORT = 65535
DASHBOARD_ENV_PREFIX = "CAUDAL_SIM_DASHBOARD_"


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
