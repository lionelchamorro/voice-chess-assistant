"""Example server entrypoint."""

from pathlib import Path

from voice_chess_server.core.config import Settings
from voice_chess_server.main import create_app, run

EXAMPLE_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_AUTO_DEMO_PROMPT = (
    "Start the voice demo automatically. The board has already been advanced through this opening "
    "sequence: e2 to e4, e7 to e5, g1 to f3, b8 to c6, f1 to b5. Introduce yourself in one short "
    "sentence, explain the ideas behind that sequence in plain language, and invite the user to "
    "interrupt at any time. Do not call board-manipulation, annotation, or highlight tools during "
    "this automatic explanation unless the user explicitly asks for them."
)
SETTINGS = Settings(_env_file=EXAMPLE_ENV_FILE if EXAMPLE_ENV_FILE.exists() else None).model_copy(
    update={
        "auto_start_demo_on_voice_connect": True,
        "auto_start_demo_prompt": DEFAULT_AUTO_DEMO_PROMPT,
    }
)

app = create_app(settings=SETTINGS)

__all__ = ["app", "run"]
