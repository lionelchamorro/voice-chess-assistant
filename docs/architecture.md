# Architecture

## Runtime split

The system is split into three layers:

1. Protocol layer
   `packages/voice-chess-core`
   Defines the canonical board WebSocket contract.

2. Backend runtime
   `packages/voice-chess-server`
   Owns session state, chess legality, Pipecat voice runtime and transport signaling.

3. Frontend runtime
   `packages/voice-chess-react`
   Owns board session state in React, emits user commands and renders a controlled board.

## Canonical state

The backend is the source of truth for:

- legal moves
- FEN / PGN state
- review mode vs live mode
- annotations and highlights

The frontend may be optimistic for UX, but it reconciles against server events.

## Transport split

- Voice transport: `smallwebrtc` via `/api/offer`
- Board state sync: WebSocket via `/ws/sessions/{session_id}/board`

This separation keeps low-latency media handling independent from board-domain events.

## Tooling path

The Pipecat LLM runtime registers tools that call into the `SessionManager`.

Current tool set:

- `get_board_state`
- `load_position`
- `load_pgn`
- `make_move`
- `reset_board`
- `set_highlights`
- `set_annotations`

Each tool mutates or inspects canonical board state, then broadcasts protocol events to the frontend.
