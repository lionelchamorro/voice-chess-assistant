# Voice Chess Assistant

Reusable monorepo for a React chess board UI plus a Python Pipecat backend that
can speak, reason about a game, and control the board over WebSocket.

## What is included

- `@voice-chess/core`: protocol types, JSON schemas and fixtures
- `@voice-chess/react`: provider, hooks, controlled board UI, browser voice transport and status widgets
- `voice-chess-server`: reusable FastAPI + Pipecat backend package
- `examples/server`: runnable backend wrapper
- `examples/web`: runnable Vite app
- `tests/e2e`: Playwright coverage for the example flow

## Workspace Layout

- `examples/web`: example web application
- `examples/server`: example backend application
- `packages/voice-chess-react`: reusable React library
- `packages/voice-chess-core`: shared frontend protocol package
- `packages/voice-chess-server`: reusable Python backend library
- `packages/voice-chess-testkit`: shared Python test helpers
- `tests/e2e`: end-to-end tests

## Package Managers

- Node workspaces: `pnpm`
- Python workspaces: `uv`

## Run the examples with Cartesia, OpenAI and Deepgram

1. Install dependencies:

```bash
pnpm install
uv sync --project packages/voice-chess-server --extra voice --group dev
uv sync --project examples/server
```

2. Create the example server env file from [.env.example](.//Users/lionelchamorro/Projects/personal/voice-chess-assisstant/examples/server/.env.example):

```bash
cp examples/server/.env.example examples/server/.env
```

3. Fill these variables in `examples/server/.env`:

```dotenv
VOICE_CHESS_LLM_PROVIDER=openai
VOICE_CHESS_LLM_MODEL=gpt-4o-mini
VOICE_CHESS_STT_PROVIDER=deepgram
VOICE_CHESS_TTS_PROVIDER=cartesia
VOICE_CHESS_OPENAI_API_KEY=...
VOICE_CHESS_DEEPGRAM_API_KEY=...
VOICE_CHESS_CARTESIA_API_KEY=...
VOICE_CHESS_CARTESIA_VOICE_ID=...
VOICE_CHESS_CARTESIA_MODEL=sonic-3
```

4. Start the backend:

```bash
uv run --project examples/server uvicorn voice_chess_example_server.main:app --host 0.0.0.0 --port 7860
```

5. Start the web example in another terminal:

```bash
pnpm --filter @voice-chess/example-web dev
```

6. Open the web app, click `Connect` for the board session, then click `Start voice`.
   The browser should request microphone permission and the remote assistant audio
   will play back in the embedded audio control.

The web app expects the board socket at `ws://localhost:7860/ws/sessions` and
the signaling API at `http://localhost:7860` by default. The backend also
exposes health at `http://localhost:7860/health`.

## How to extend the library

### Frontend

Compose your own UI around `VoiceChessProvider`, the board primitives, and the
voice transport controls:

```tsx
import {
  VoiceChessBoard,
  VoiceChessProvider,
  VoiceChessVoiceControls,
  useVoiceChessSession,
} from "@voice-chess/react";

function Toolbar() {
  const { connectionStatus, resetBoard } = useVoiceChessSession();
  return (
    <div>
      <span>{connectionStatus}</span>
      <button onClick={resetBoard}>Reset</button>
    </div>
  );
}

export function App() {
  return (
    <VoiceChessProvider
      boardSocketUrl="ws://localhost:7860/ws/sessions"
      signalingApiUrl="http://localhost:7860"
      sessionId="analysis-session"
      autoConnect={false}
    >
      <Toolbar />
      <VoiceChessVoiceControls />
      <VoiceChessBoard />
    </VoiceChessProvider>
  );
}
```

### Backend

`create_app()` now accepts a `Settings` instance and an `orchestrator_factory`,
so you can swap prompts, providers or tool registration without editing the
library package in place:

```python
from voice_chess_server import create_app
from voice_chess_server.core.config import Settings
from voice_chess_server.services.orchestrator import BotOrchestrator


class MyOrchestrator(BotOrchestrator):
    pass


settings = Settings(
    tts_provider="cartesia",
    stt_provider="deepgram",
    llm_provider="openai",
)

app = create_app(
    settings=settings,
    orchestrator_factory=lambda settings, session_manager: MyOrchestrator(
        settings=settings,
        session_manager=session_manager,
    ),
)
```

The main extension seams today are:

- `Settings` for provider and runtime configuration
- `BotOrchestrator` for LLM/STT/TTS wiring and tool registration
- `SessionManager` for canonical board state and domain events
- `VoiceChessProvider` for browser signaling and unified board + voice session state
- `@voice-chess/core` for the cross-platform protocol contract

## Documentation

- `docs/setup.md`
- `docs/architecture.md`
- `docs/integration.md`
