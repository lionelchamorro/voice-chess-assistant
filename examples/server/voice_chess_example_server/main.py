"""Example server entrypoint."""

from pathlib import Path

from voice_chess_server.core.config import Settings
from voice_chess_server.main import create_app, run

EXAMPLE_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_AUTO_DEMO_PROMPT = (
    "Comienza la lección ahora, hablando siempre en español. Enseña los primeros cinco "
    "movimientos de la Apertura Española (Ruy López) como UNA sola narración continua "
    "usando marcas en línea, colocando cada marca exactamente donde el movimiento "
    "corresponde en tu discurso. Empieza reiniciando el tablero y luego cubre e4, e5, "
    "Nf3, Nc6 y Bb5 — una idea breve por movimiento, con su marca en el momento en que "
    'lo nombras. Ejemplo del estilo esperado: "Preparemos las piezas. [[reset]] Las '
    "blancas abren con peón cuatro rey [[move e2e4]], reclamando el centro, y las negras "
    'responden simétrico [[move e7e5]] para no ceder terreno..." Continúa con ese mismo '
    "ritmo con el caballo a efe tres [[move g1f3]], el caballo a ce seis [[move b8c6]] y "
    "el alfil a be cinco [[move f1b5]]. No llames herramientas del tablero para este "
    "recorrido — las marcas hacen los movimientos. Nunca leas una marca en voz alta ni "
    "menciones herramientas o que el tablero se actualiza; habla solo de las ideas. "
    "Después de Bb5, invita al alumno a interrumpirte con preguntas o a cargar una "
    "partida para repasarla juntos."
)
SETTINGS = Settings(_env_file=EXAMPLE_ENV_FILE if EXAMPLE_ENV_FILE.exists() else None).model_copy(
    update={
        "auto_start_demo_on_voice_connect": True,
        "auto_start_demo_prompt": DEFAULT_AUTO_DEMO_PROMPT,
    }
)

app = create_app(settings=SETTINGS)

__all__ = ["app", "run"]
