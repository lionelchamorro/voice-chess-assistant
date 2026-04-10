# @voice-chess/core

Source-of-truth package for the voice chess assistant protocol.

## Contents

- `src/`: TypeScript protocol types
- `schemas/`: JSON Schemas for client commands and server events
- `fixtures/`: representative protocol messages for tests and examples

## Protocol Scope

This package defines the WebSocket contract between the browser and backend for:

- session readiness and errors
- canonical board synchronization
- manual user move requests
- PGN and FEN loading
- PGN navigation
- annotations and highlights emitted by the agent/backend

The backend remains the source of truth. The frontend can be optimistic for UX,
but every meaningful state transition must reconcile against server messages.
