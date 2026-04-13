import { useVoiceChessSession } from "../hooks/useVoiceChessSession";

export function VoiceChessStatus() {
  const {
    connectionStatus,
    conversationState,
    voiceConnectionStatus,
    voiceTransportAvailable,
    microphonePermissionStatus,
    errorMessage,
    voiceErrorMessage,
    boardState,
  } = useVoiceChessSession();

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
      <span data-testid="conversation-state">Conversation: {conversationState}</span>
      <span data-testid="voice-connection-status">Voice: {voiceConnectionStatus}</span>
      <span data-testid="voice-availability-status">
        Voice available: {voiceTransportAvailable ? "yes" : "no"}
      </span>
      <span data-testid="microphone-permission-status">Mic: {microphonePermissionStatus}</span>
      <span data-testid="board-view">View: {boardState?.viewMode ?? "unknown"}</span>
      <span data-testid="board-turn">Turn: {boardState?.turn ?? "unknown"}</span>
      {errorMessage ? (
        <span data-testid="board-error" style={{ color: "#b91c1c" }}>
          Error: {errorMessage}
        </span>
      ) : null}
      {voiceErrorMessage ? (
        <span data-testid="voice-error" style={{ color: "#b91c1c" }}>
          Voice error: {voiceErrorMessage}
        </span>
      ) : null}
    </div>
  );
}
