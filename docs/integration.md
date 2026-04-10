# Integration

## React integration

Wrap your app with `VoiceChessProvider`:

```tsx
import { VoiceChessBoard, VoiceChessProvider } from "@voice-chess/react";

export function App() {
  return (
    <VoiceChessProvider
      boardSocketUrl="ws://localhost:7860/ws/sessions"
      sessionId="demo-session"
    >
      <VoiceChessBoard />
    </VoiceChessProvider>
  );
}
```

## Backend integration

Import the reusable FastAPI app factory:

```python
from voice_chess_server import create_app

app = create_app()
```

## Protocol contract

Client commands and server events are defined in `@voice-chess/core`.

Key command types:

- `board.request_move`
- `board.navigate`
- `board.request_load_fen`
- `board.request_load_pgn`
- `board.request_reset`

Key server event types:

- `session.ready`
- `session.error`
- `board.state`
- `board.move_applied`
- `board.annotation_set`
- `board.highlight_set`
- `board.reset`
