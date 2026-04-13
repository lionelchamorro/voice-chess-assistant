# @voice-chess/react

Reusable React package for the voice chess assistant frontend.

## Current Scope

- session provider for board WebSocket state
- session provider for browser voice signaling and remote audio playback
- hooks for connection state and board commands
- controlled board UI with manual move requests
- PGN navigation helpers through the provider API

## Design

The package is split into:

- headless session state and command helpers
- presentational React primitives

The backend remains the source of truth. The board component can emit move
intentions, but every state transition is reconciled from server events.
