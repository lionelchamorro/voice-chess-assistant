# Example Server

Minimal runnable server application that wraps `voice-chess-server`.

## Purpose

- load environment defaults for local development
- expose the reusable FastAPI app from the server package
- serve as the entrypoint for the demo stack

## Environment

When present, `examples/server/.env` is loaded explicitly by the example
wrapper before creating the app settings. Use `examples/server/.env.example`
as the starting point for local voice provider credentials.

## Voice Runtime

The example server depends on `voice-chess-server[voice]`, so after pulling
changes you should run `uv sync` in `examples/server` to install the Pipecat
runtime and provider integrations used by `Join voice`.
