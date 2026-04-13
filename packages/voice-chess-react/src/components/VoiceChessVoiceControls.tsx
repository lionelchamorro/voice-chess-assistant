import { useEffect, useRef } from "react";

import { useVoiceChessSession } from "../hooks/useVoiceChessSession";

export function VoiceChessVoiceControls() {
  const {
    voiceConnectionStatus,
    voiceTransportAvailable,
    voiceTransportReason,
    microphonePermissionStatus,
    voiceErrorMessage,
    remoteAudioStream,
    connectVoice,
    disconnectVoice,
  } = useVoiceChessSession();
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const audioElement = audioRef.current;
    if (!audioElement) {
      return;
    }

    audioElement.srcObject = remoteAudioStream;
    if (remoteAudioStream) {
      void audioElement.play().catch(() => {
        // The browser can still block autoplay in some environments even after joining the call.
      });
    }
    return () => {
      audioElement.pause();
      audioElement.srcObject = null;
    };
  }, [remoteAudioStream]);

  return (
    <div
      data-testid="voice-controls"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div>
          <strong>Voice session</strong>
          <div style={{ marginTop: 4, color: "#64748b", fontSize: "0.95rem" }}>
            Status: {voiceConnectionStatus} · Mic: {microphonePermissionStatus}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" onClick={() => void connectVoice()} disabled={!voiceTransportAvailable}>
            Join voice
          </button>
          <button type="button" onClick={disconnectVoice}>
            Leave voice
          </button>
        </div>
      </div>
      <p style={{ margin: 0, color: "#475569", fontSize: "0.92rem" }}>
        Joining voice starts the live opening demo automatically, and you can interrupt the assistant
        at any time.
      </p>
      {!voiceTransportAvailable ? (
        <p data-testid="voice-unavailable" style={{ margin: 0, color: "#b45309", fontSize: "0.92rem" }}>
          Voice unavailable: {voiceTransportReason ?? "Server voice runtime is not ready."}
        </p>
      ) : null}
      {voiceErrorMessage ? (
        <p data-testid="voice-error-inline" style={{ margin: 0, color: "#b91c1c", fontSize: "0.92rem" }}>
          {voiceErrorMessage}
        </p>
      ) : null}
      <audio ref={audioRef} autoPlay playsInline style={{ display: "none" }} />
    </div>
  );
}
