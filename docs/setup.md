# Setup

## Overview

This monorepo contains:

- `packages/voice-chess-core`: shared protocol types, schemas and fixtures
- `packages/voice-chess-react`: React provider, hooks and controlled board UI
- `packages/voice-chess-server`: FastAPI + Pipecat backend library
- `examples/web`: Vite demo application
- `examples/server`: minimal backend wrapper
- `tests/e2e`: Playwright tests

## Python

Primary backend package:

```bash
uv sync --project packages/voice-chess-server --extra voice --group dev
```

Example server:

```bash
uv sync --project examples/server
uv run --project examples/server uvicorn voice_chess_example_server.main:app --host 0.0.0.0 --port 7860
```

## Frontend

Install workspace dependencies:

```bash
pnpm install
```

Run the example web app:

```bash
cd examples/web
pnpm dev
```

## Environment

Backend voice runtime expects these variables for the current provider set:

- `VOICE_CHESS_OPENAI_API_KEY`
- `VOICE_CHESS_DEEPGRAM_API_KEY`
- `VOICE_CHESS_CARTESIA_API_KEY`
- `VOICE_CHESS_CARTESIA_VOICE_ID`
- `VOICE_CHESS_CARTESIA_MODEL` optional, defaults to `sonic-3`
- `VOICE_CHESS_TTS_PROVIDER=cartesia`

Example server defaults are documented in `examples/server/.env.example`.
