# Voice Chess Assistant Plan

## Goal

Construir un monorepo profesional con:

- una libreria React reutilizable para voz + tablero de ajedrez
- una libreria Python reutilizable para backend Pipecat + control de tablero
- una web de ejemplo funcionando end-to-end
- CI separada para frontend, backend y e2e

## References Used

- `~/.claude/CLAUDE.md`
- `~/.claude/rules/python.md`
- `~/.claude/rules/fastapi.md`
- `~/Projects/collective/catalyst/.github/workflows/backend-ci.yml`
- `~/Projects/collective/catalyst/.github/workflows/frontend-ci.yml`
- `~/Projects/collective/catalyst/.github/workflows/e2e.yml`
- `~/Projects/collective/catalyst/prek.toml`
- `~/Projects/collective/local-voice-assistant`

## Key Decisions

- Voz en browser a backend por Pipecat `smallwebrtc` para baja latencia.
- Control del tablero por WebSocket separado del canal de audio.
- El usuario puede mover piezas manualmente; el backend valida y reconcilia.
- Frontend y backend como librerias separadas, mas apps de ejemplo.
- Configuracion de LLM, STT y TTS via adapters y `pydantic-settings`.
- CI con proveedores mockeados para evitar dependencias externas en tests.
- `Playwright` es el framework e2e/UI. `Pyright` es para type checking.

## Monorepo Shape

```text
.
├── examples/
│   ├── web/
│   └── server/
├── packages/
│   ├── voice-chess-core/
│   ├── voice-chess-react/
│   ├── voice-chess-server/
│   └── voice-chess-testkit/
├── tests/
│   └── e2e/
├── tasks/
│   └── todo.md
├── .github/
│   └── workflows/
├── package.json
├── pnpm-workspace.yaml
├── pyproject.toml
├── uv.lock
└── prek.toml
```

## Package Responsibilities

### `packages/voice-chess-react`

Publica una libreria tipo `@voice-chess/react` con:

- `VoiceChessProvider`
- `PipecatTransportProvider`
- `ChessBoard`
- `AnalysisOverlay`
- hooks como `useChessBoardState`, `useBoardSocket`, `useVoiceSession`
- componentes controlados y headless para integracion en apps externas

Decisiones tecnicas:

- React 19 + TypeScript strict
- `chess.js` para reglas, SAN/UCI/FEN/PGN
- `chessground` como base del tablero por robustez en analisis, highlights y arrows
- build con `tsup`
- peer deps para React y transportes Pipecat

### `packages/voice-chess-core`

Define el contrato entre frontend y backend:

- JSON schemas para mensajes WebSocket
- tipos TypeScript
- fixtures de ejemplo
- versionado del protocolo

Eventos iniciales:

- `session.ready`
- `session.error`
- `board.state`
- `board.move_applied`
- `board.annotation_set`
- `board.highlight_set`
- `board.reset`

La UI no debe depender de comandos ad hoc. Solo reacciona a eventos de dominio.

### `packages/voice-chess-server`

Publica la libreria Python reusable con:

- `create_app(settings: Settings) -> FastAPI`
- session manager para audio + board channel
- router `/api/offer` para `smallwebrtc`
- router `/ws/sessions/{session_id}/board`
- providers configurables para LLM, STT y TTS
- registro de tools del LLM
- serializers del protocolo de tablero

Stack objetivo:

- Python 3.12
- `uv` + `pyproject.toml`
- FastAPI
- Pydantic v2
- `structlog`
- `anyio`
- Pipecat

### `packages/voice-chess-testkit`

Soporte para tests deterministas:

- fake LLM que emite tool calls predefinidos
- fake STT/TTS opcionales
- fixtures para sesiones y snapshots de eventos
- utilidades para correr e2e sin credenciales reales

### `examples/web`

Demo real que consume la libreria React y el backend de ejemplo.

Flujos minimos:

- conectar microfono
- hablar con el agente
- cargar FEN/PGN
- pedir analisis
- ver al agente mover piezas y anotar el tablero

### `examples/server`

App minima que importa `voice_chess_server`, carga settings y registra:

- prompt del agente ajedrecistico
- tools de tablero
- configuracion de proveedores
- endpoints de health

## Backend Design

### Session Model

Cada sesion mantiene:

- estado de Pipecat
- estado canonico del tablero
- historial de eventos
- contexto conversacional
- metadata de proveedor y tracing

El backend es la fuente de verdad del tablero. El frontend nunca decide legalidad final.

### Board Domain

Modelo canonico:

- `fen`
- `pgn`
- turno
- orientacion
- legal moves
- annotations
- selected squares

Libreria sugerida:

- `python-chess` para validacion, PGN, FEN y lineas de analisis

### LLM Tools

Tools minimas:

- `get_board_state`
- `load_position`
- `load_pgn`
- `make_move`
- `undo_move`
- `reset_board`
- `set_highlight`
- `clear_highlights`
- `set_annotation`

Reglas:

- el tool no toca UI directamente
- el tool muta estado de dominio
- el backend emite evento WebSocket
- el tool devuelve un resultado compacto para que el LLM continue hablando

### Provider Configuration

Config por `pydantic-settings`:

- `LLM_PROVIDER`
- `LLM_MODEL`
- `STT_PROVIDER`
- `TTS_PROVIDER`
- credenciales por provider
- flags para `mock` y `record/replay`

Combinacion default recomendada para desarrollo local:

- LLM: OpenAI
- STT: Deepgram
- TTS: ElevenLabs

## Frontend Design

### Library API

La libreria React debe soportar dos niveles:

- opinionated: provider + tablero + panel de voz listos para usar
- headless: hooks y estado para integracion en producto propio

### Board Sync

El board recibe eventos WebSocket y actualiza estado local optimista solo para UX. El backend reconcilia siempre.

El flujo de interaccion manual queda asi:

- el usuario mueve en frontend
- el frontend envia intencion de jugada al backend
- el backend valida legalidad y estado de sesion
- el backend emite el nuevo `board.state` canonico
- el frontend reconcilia

### Voice Transport

El cliente usa Pipecat React/client packages para:

- inicializar transporte
- conectar/desconectar
- manejar estado de microfono
- exponer transcript y errores

### Example UX

Pantalla unica inicial:

- tablero central
- transcript lateral
- controles de microfono
- controles para FEN/PGN
- lista de movimientos
- navegacion completa por PGN
- indicadores visuales cuando mueve el usuario vs cuando mueve el agente

## Testing Strategy

### Frontend

- `vitest` + Testing Library para componentes y hooks
- `tsc --noEmit` para typecheck

### Backend

- `pytest`
- `pytest-asyncio`
- tests de protocolo
- tests de tools del tablero
- tests de FastAPI y WebSocket

### E2E

- `Playwright`
- flujo determinista con backend mock
- verificar conexion, transcript, tool calls y sincronizacion del tablero

No depender de microfono real ni APIs de terceros en CI.

## CI/CD

### Backend CI

Basado en `catalyst/backend-ci.yml`:

- checkout
- setup Python 3.12
- install `uv`
- `uv sync --dev`
- install `prek`
- correr `uvx prek run --files ...`
- correr `pytest`

### Frontend CI

Basado en `catalyst/frontend-ci.yml`:

- checkout
- setup `pnpm`
- setup Node 20
- `pnpm install --frozen-lockfile`
- `pnpm -r typecheck`
- `pnpm -r test`
- `pnpm -r build`

### E2E CI

Basado en `catalyst/e2e.yml`:

- levantar `example-server` + `example-web`
- instalar Playwright browsers
- correr e2e
- subir reporte HTML

## Pre-commit

Tomar `prek.toml` como base y adaptarlo:

- `uv-lock`
- `check-merge-conflict`
- `check-added-large-files`
- `check-toml`
- `check-yaml`
- `end-of-file-fixer`
- `trailing-whitespace`
- `validate-pyproject`
- `ruff-format`
- `ruff --fix --exit-non-zero-on-fix`
- type checker Python estricto

Para frontend agregar:

- TypeScript/JSON/YAML checks
- formatter/linter de JS/TS

## Implementation Phases

- [x] Bootstrap del monorepo con `pnpm-workspace.yaml`, root `package.json`, root `pyproject.toml` y `uv.lock`
- [x] Crear `packages/voice-chess-core` con schemas, tipos y fixtures
- [x] Crear `packages/voice-chess-server` con settings, app factory y session manager
- [x] Implementar board domain con `python-chess`
- [x] Implementar navegacion PGN y timeline de jugadas
- [x] Implementar tools del LLM y bridge a eventos WebSocket
- [x] Integrar Pipecat `smallwebrtc` y providers configurables
- [x] Crear `packages/voice-chess-react` con provider, hooks y tablero controlado
- [x] Crear `examples/server`
- [x] Crear `examples/web`
- [x] Agregar tests unitarios backend/frontend
- [x] Agregar `tests/e2e` con Playwright
- [x] Agregar GitHub Actions para backend, frontend y e2e
- [x] Agregar docs de setup, arquitectura y ejemplos de integracion

## Main Risks

- Pipecat audio path y board WebSocket requieren coordinacion de session IDs.
- Tests e2e con audio real serian fragiles; por eso hace falta modo mock oficial.
- Function calling del LLM puede generar comandos ambiguos; hay que normalizar SAN/UCI.
- El board debe permitir control remoto sin romper interaccion manual del usuario.
- La navegacion PGN requiere diferenciar entre estado explorado y estado vivo de la sesion.

## Open Product Decisions

- Resuelto: el usuario puede mover piezas manualmente y el backend valida/rechaza en tiempo real.
- Resuelto: v1 soporta solo `smallwebrtc`.
- Resuelto: v1 analiza tanto la posicion actual como PGN completo con navegacion por jugadas.

## Review

- Estado: plan de arquitectura listo para implementacion.
- Enfoque recomendado: monorepo mixto `pnpm` + `uv`, librerias separadas y demo real.
- Criterio de calidad: tipado estricto, providers desacoplados, protocolo versionado, mocks para CI, Playwright para e2e.
- Scope v1 cerrado: interaccion manual del usuario, transporte `smallwebrtc`, posicion actual y PGN navegable.
- Bootstrap completado: estructura base creada para workspaces Node y Python con nombres de carpetas orientados a producto.
- Core protocol listo: tipos TypeScript, JSON Schema y fixtures base para comandos y eventos del tablero.
- Server package base listo: settings, app factory, signaling HTTP, WebSocket del board y session manager con `python-chess`.
- Validacion local backend completada: sintaxis Python 3.12, parseo de JSON/TOML, `pytest` backend, import de app factory, import del example server, smoke check de `/health` y carga del runtime Pipecat.
- Validacion local frontend completada: `tsc` en `@voice-chess/core`, `@voice-chess/react` y `examples/web`, `vitest` en `@voice-chess/react` y build de Vite del example web.
- E2E validado en entorno local con Playwright: arranque automatico de backend/frontend, conexion WebSocket, carga de FEN demo y reset del tablero.
- React package base listo: provider de sesion, hook de board socket y tablero controlado para jugadas manuales.
- Example apps listos: wrapper server minimo y Vite demo para board session, FEN, PGN y navegacion.
- Verificacion base lista: tests unitarios, Playwright e2e, workflows CI y `prek.toml`.
- Runtime Pipecat listo por codigo: orchestrator, providers y tools conectadas al estado canonico del tablero.
- Documentacion base lista: setup, arquitectura e integracion.
