# Lessons

- Auto demos must be idempotent across reconnects. If a demo depends on a known board state, reset the board explicitly before the first scripted move instead of assuming a fresh session.
- LLM tool handlers must validate missing or malformed arguments defensively. Even when a schema marks fields as required, models can still emit partial tool calls during real sessions.
