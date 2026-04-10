# voice-chess-server

Reusable Python backend library for Pipecat voice orchestration, chess board
state, tool execution and WebSocket synchronization.

## Current Scope

- FastAPI app factory with lifespan and timing middleware
- `smallwebrtc` signaling endpoint at `/api/offer`
- board WebSocket at `/ws/sessions/{session_id}/board`
- session manager for board state and client broadcasts
- `python-chess` based board domain with FEN, PGN and move navigation

## Notes

The signaling layer loads Pipecat lazily so the package can be imported without
the transport runtime installed. The voice pipeline orchestration and board
tools are wired through the optional `voice` extra.
