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

## Active Remediation Plan

- [x] Agregar tools faltantes del agente: `undo_move`, `clear_highlights` y normalizar `set_highlight` vs `set_highlights`.
- [x] Extender el protocolo con eventos de conversacion y transcript para la demo (`voice.state`, `conversation.message`, `tool.call`).
- [x] Implementar estado conversacional canonico por sesion en backend para `listening`, `thinking` y `speaking`.
- [x] Agregar un flujo demo/mock determinista para voz y transcript sin depender de STT/TTS reales en E2E.
- [x] Rediseñar `examples/web` como voicebot: transcript visible, mensajes usuario/asistente, estado conversacional y audio remoto sin controles visibles.
- [x] Actualizar Playwright para validar transcript, tool calls del agente y sincronizacion del tablero a partir del flujo mock.
- [x] Revalidar con `pytest`, `vitest`, `tsc` y `playwright` antes de cerrar.

## V2 Rearchitecture Plan (2026-07-02, pendiente de aprobacion)

Diagnostico: el camino de voz real (Pipecat) nunca alimenta la UI (transcript y
`voice.state` solo los emite el simulador regex `run_demo_prompt`), no existe
sincronizacion voz-tablero, el WebRTC del front es artesanal y sin `iceServers`,
y los tool handlers no manejan errores. El producto "profesor que mueve piezas"
requiere re-cablear el runtime, no parches.

### Fase 1 — Adoptar RTVI end-to-end

- [x] Back: `TranscriptProcessor` + `BoardBridgeObserver` (BaseObserver local
      a `run_transport`) en el pipeline real; emiten `conversation.message`
      y `voice.state` genuinos (listening/thinking/speaking) por el board
      socket, ya no solo el simulador. Ver `orchestrator.py::run_transport`.
- [ ] Front: reemplazar `useVoiceTransport` artesanal por
      `@pipecat-ai/client-js` + `@pipecat-ai/small-webrtc-transport` — no
      hecho en esta pasada (cambio grande, requiere nueva dependencia npm;
      se optó por arreglar el WebRTC artesanal en su lugar: `iceServers` +
      timeout de ICE gathering).
- [ ] Mover el simulador regex de `SessionManager.run_demo_prompt` a
      `voice-chess-testkit` — no hecho, deferido (sigue siendo el único
      camino determinista para e2e sin credenciales reales).
- [x] Registro de pipelines por sesion (`BotOrchestrator._active_sessions`):
      una oferta nueva para el mismo `session_id` cancela la anterior;
      cleanup en `finally` con chequeo de identidad para evitar razas.
      Excepciones del pipeline ahora se loguean (antes las tragaba
      `BackgroundTasks` en silencio).

### Fase 2 — El profesor de verdad

- [x] Tool `analyze_position` con Stockfish real via `chess.engine` (async,
      degrada con error claro si el binario no está disponible). Probado
      contra Stockfish 18 real, incluye detección de mate forzado.
- [x] Modelo docente: default subido a gpt-4o (Settings, README, .env.example)
      — gpt-4o-mini abandonaba secuencias largas de tool calls (solo jugaba
      la primera movida del demo y narraba el resto sin ejecutar).
- [x] Repaso de partidas + variantes (2026-07-02, tercera pasada): tools
      `show_next_move`/`show_previous_move`/`go_to_move`/`return_to_live`
      para recorrer una partida cargada ply a ply (mueve ambos bandos,
      paced con la voz), y sandbox de variantes `play_variation_move`/
      `end_variation` sobre la posición revisada sin tocar la partida
      (BoardSessionState.variation_moves; campo `variation` en BoardState +
      chip "sideline" en la UI). `make_move` acepta SAN además de
      coordenadas, promociona a dama por defecto, y `lastMove` ahora refleja
      la jugada visible durante el review (arregla tinte/animación del
      tablero al navegar). Prompts reescritos: prohibido narrar mecánica
      ("ahora muevo la pieza"), disciplina de continuación con ejemplo
      literal del ritmo frase→jugada.
- [x] Sincronia voz-tablero implementada (2026-07-02, segunda pasada):
      `SpeechPacer` en `orchestrator.py` — las tools que mutan el tablero
      (make_move, undo, reset, load_fen/pgn, highlights, annotations)
      esperan a que el audio del turno actual empiece a sonar
      (`BotStartedSpeakingFrame` + lead de 0.6s) antes de aplicar el cambio.
      Si el turno no tiene texto hablado, no se demora nada; timeout de 2s
      como red de seguridad. Config: `speech_pacing_*` en Settings.
      Ademas se eliminó el demo scripteado (`_run_auto_demo_setup`): ahora
      el propio LLM enseña la apertura via prompt "una frase corta → una
      jugada", así el tablero sigue a la voz también en el demo. El system
      prompt fuerza el patrón anuncio-antes-de-tool.
- [x] Jugadas manuales del usuario inyectadas al contexto del LLM en vivo
      via `SessionManager.set_manual_move_hook` → `BotOrchestrator
      .notify_manual_move` → `LLMMessagesAppendFrame` en la pipeline activa.

### Fase 3 — Robustez y produccion

- [x] try/except en todos los tool handlers (`BotOrchestrator._tool_handler`):
      `BoardCommandError` → error tipado al LLM, argumentos inválidos →
      `invalid_arguments`, cualquier otra excepción → `internal_error`
      logueado. El turno del asistente ya no se cuelga.
- [x] `broadcast` tolerante a sockets muertos (captura `RuntimeError` además
      de `WebSocketDisconnect`).
- [x] `iceServers` configurable en el cliente (prop `iceServers` en
      `VoiceChessProvider`, default STUN de Google) + timeout de ICE
      gathering (4s) para no colgar `connecting` para siempre.
- [ ] Auth (token efímero por sesión) — no implementado, sigue abierto.
- [ ] Lifecycle: TTL de sesiones / limpieza de mensajes y tool calls — no
      implementado, sigue creciendo sin límite en memoria.
- [x] Investigado compartir `LocalSmartTurnAnalyzerV3`: **descartado**, es
      stateful por conexión (`_audio_buffer`, `_speech_triggered`);
      compartirlo mezclaría audio entre sesiones concurrentes. El costo de
      cargar el modelo ONNX por conexión es inherente a esta clase de
      Pipecat tal como está, no hay seam para inyectar una sesión
      compartida sin fork de la librería.
- [x] Reconexión con backoff exponencial (500ms→8s) en `useBoardSocket`,
      solo cuando la desconexión no fue manual (`disconnect()` no reintenta).
- [x] E2E arreglado de raíz: `App.tsx` nunca renderizaba `conversationMessages`
      pese a que el provider ya los exponía (bug real, no solo el test).
      Se agregó el panel de transcript (`data-testid="conversation-messages"`)
      y ahora el spec de Playwright pasa contra el flujo real, no solo se
      hizo pasar el test.
- [ ] Dockerfile + métricas Pipecat + límites de gasto por sesión — no
      implementado, sigue abierto.

**Hallazgos adicionales durante la verificación (no en el plan original):**

- `OpenAILLMService(model=...)` estaba usando un parámetro deprecado de
  Pipecat 0.0.108; corregido a `settings=OpenAILLMService.Settings(model=...)`.
- `pyright --strict` y `ruff check` **ya estaban rotos en `main`** antes de
  esta sesión (370 errores de pyright, 20+ de ruff N806 solo en
  `orchestrator.py`, más S101 pendiente en toda la suite de tests). No es
  una regresión introducida acá — de hecho el conteo de pyright bajó a 277
  al consolidar los tool handlers. Se dejó documentado en vez de intentar
  un lint-cleanup completo y no relacionado al pedido.
- En este entorno sandboxeado de desarrollo, el primer handshake WebSocket
  de Chromium hacia `localhost` se colgaba indefinidamente (HTTP normal
  funcionaba bien) hasta un primer "warm-up" del sandbox de macOS; no es un
  bug de la app — se verificó con un cliente WebSocket Python crudo contra
  el mismo backend, que conectó al instante. No requirió cambios de código.

## Speech-sync v2 (2026-07-02, cuarta pasada)

Regresión reportada con gpt-4o: emitía todas las tool calls en paralelo y sin
texto previo (una completion solo-tools), así que el pacer no tenía voz con
qué sincronizar y el tablero se jugaba entero antes del audio.

- [x] `parallel_tool_calls: False` en el request de OpenAI (via
      `Settings.extra`) — una tool call por completion, imposible batchear
      las 5 jugadas en un respiro.
- [x] Argumento `say` en todas las tools que mutan el tablero: la narración
      viaja DENTRO del tool call; el server la habla via `TTSSpeakFrame` y
      retiene la jugada hasta que ese audio empieza (`SpeechPacer
      .await_speaking`). Sync garantizado estructuralmente, sin depender de
      que el modelo escriba texto antes del tool call. Si el modelo sí
      narró en el stream, `say` se ignora para no duplicar voz.
- [x] `enable_rtvi=False` en `PipelineTask`: el cliente browser no abre data
      channel, así que el RTVIProcessor solo llenaba la cola de mensajes del
      transporte ("Message queue is full (50 messages)" cada pocos ms).
- [x] Prompts reescritos alrededor de `say` (system + demo con ejemplo
      literal `make_move(san='e4', say='White opens with e4...')`).

## Narrated Action Stream (2026-07-03, quinta pasada)

Implementado el Tier 1 de docs/speech-action-sync.md: sincronización a nivel
de palabra entre voz y tablero via marcas inline.

- [x] `services/narration.py`: `StreamMarkerParser` (parseo incremental de
      `[[...]]` seguro ante marcas partidas entre chunks del stream, holdback
      de prefijos, drop de marcas sin cerrar en flush), `ChoreographyState`
      (cues anclados a offset de texto limpio, disparo cuando el contador de
      playout cruza el anchor, secuencias generación/playout independientes
      para que cues de una completion futura no disparen contra el audio de
      la anterior, drain en BotStoppedSpeaking, clear en interrupción).
- [x] Orchestrator: `_NarrationMarkerProcessor` (entre llm y tts — quita
      marcas antes de que el TTS las vea) y `_ActionSchedulerProcessor`
      (después de transport.output(), donde los TTSTextFrame llegan word-
      alineados por el clock de pts del transport). `execute_narrated_action`
      despacha move/next/prev/reset/var/endvar/highlight/clear al
      SessionManager con trace en el Engine room y tolerancia a marcas
      ilegales/desconocidas.
- [x] Prompts: system prompt enseña el DSL de marcas como via principal de
      demostración (tools quedan para lo que necesita resultado); demo
      prompt = una sola narración continua con marcas.
- [x] Setting `narrated_actions_enabled` (default true) para bypassear los
      procesadores.
- [x] 15 tests nuevos (51 total) + simulación end-to-end generación→playout
      →tablero + build del pipeline real con los procesadores verificado
      contra pipecat 0.0.108.

## Remediation Review

- Tools del agente completadas: `undo_move`, `clear_highlights`, `set_highlight` y `set_highlights` quedaron expuestas desde el orchestrator hacia el estado canonico del tablero.
- Protocolo ampliado: la sesion ahora emite `voice.state`, `conversation.message` y `tool.call` para soportar transcript, estado conversacional y trazas del agente.
- Demo rediseñada: `examples/web` ahora prioriza conversacion, transcript, tool activity y deja el audio remoto como infraestructura sin controles visibles.
- Flujo mock para demo/E2E: se agrego `conversation.request_demo` para generar turnos deterministas con transcript, tool calls y cambios reales del tablero sin depender de proveedores externos.
- Verificacion actualizada: `pytest`, `pnpm -r typecheck`, `vitest`, build del example web y `playwright` pasan con la implementacion nueva.
