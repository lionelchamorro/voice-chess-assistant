import { useVoiceChessSession } from "../hooks/useVoiceChessSession";

export function VoiceChessStatus() {
  const { connectionStatus, errorMessage, boardState } = useVoiceChessSession();

  return (
    <div
      data-testid="voice-chess-status"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 12,
        border: "1px solid #d0d4db",
        borderRadius: 12,
        background: "#ffffff",
      }}
    >
      <strong>Session</strong>
      <span data-testid="connection-status">Status: {connectionStatus}</span>
      <span data-testid="board-view">View: {boardState?.viewMode ?? "unknown"}</span>
      <span data-testid="board-turn">Turn: {boardState?.turn ?? "unknown"}</span>
      {errorMessage ? (
        <span data-testid="board-error" style={{ color: "#b91c1c" }}>
          Error: {errorMessage}
        </span>
      ) : null}
    </div>
  );
}
