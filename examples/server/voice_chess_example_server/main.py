"""Example server entrypoint."""

from pathlib import Path

from voice_chess_server.core.config import Settings
from voice_chess_server.main import create_app, run

EXAMPLE_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
SETTINGS = Settings(_env_file=EXAMPLE_ENV_FILE if EXAMPLE_ENV_FILE.exists() else None)

app = create_app(settings=SETTINGS)

__all__ = ["app", "run"]
