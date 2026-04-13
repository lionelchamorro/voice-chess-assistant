import type {
  BoardState,
  ConversationMessage,
  ConversationState,
  ToolCallTrace,
  VoiceChessClientCommand,
  VoiceChessServerEvent,
} from "@voice-chess/core";
import type { Dispatch, SetStateAction } from "react";
import {
  createContext,
  startTransition,
  useEffect,
  useState,
} from "react";

import { useBoardSocket } from "../hooks/useBoardSocket";
import { useVoiceTransport } from "../hooks/useVoiceTransport";
import type { MoveIntent, VoiceChessProviderProps, VoiceChessSessionValue } from "../types";

export const VoiceChessContext = createContext<VoiceChessSessionValue | null>(null);

function buildCommandEnvelope<TPayload>(
  sessionId: string,
  type: VoiceChessClientCommand["type"],
  payload: TPayload,
): VoiceChessClientCommand {
  return {
    protocolVersion: "1.0.0",
    direction: "command",
    type,
    messageId: `${type}_${crypto.randomUUID()}`,
    sessionId,
    timestamp: new Date().toISOString(),
    payload,
  } as VoiceChessClientCommand;
}

export function VoiceChessProvider({
  boardSocketUrl,
  signalingApiUrl,
  sessionId,
  autoConnect = true,
  children,
}: VoiceChessProviderProps) {
  const [boardState, setBoardState] = useState<BoardState | null>(null);
  const [conversationState, setConversationState] = useState<ConversationState>("idle");
  const [conversationMessages, setConversationMessages] = useState<ConversationMessage[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCallTrace[]>([]);
  const [selectedSquare, setSelectedSquare] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [voiceErrorMessage, setVoiceErrorMessage] = useState<string | null>(null);

  const {
    connectionStatus,
    connect,
    disconnect,
    sendCommand,
  } = useBoardSocket({
    boardSocketUrl,
    sessionId,
    onEvent(event) {
      startTransition(() => {
        applyServerEvent(event, {
          setBoardState,
          setConversationState,
          setConversationMessages,
          setToolCalls,
          setErrorMessage,
          setSelectedSquare,
        });
      });
    },
    onError(message) {
      setErrorMessage(message);
    },
  });
  const {
    voiceConnectionStatus,
    voiceTransportAvailable,
    voiceTransportReason,
    microphonePermissionStatus,
    remoteAudioStream,
    connectVoice: connectVoiceTransport,
    disconnectVoice,
  } = useVoiceTransport({
    signalingApiUrl: signalingApiUrl ?? null,
    sessionId,
    onError: setVoiceErrorMessage,
  });

  useEffect(() => {
    if (!autoConnect) {
      return;
    }
    void connect();
    return disconnect;
  }, [autoConnect, connect, disconnect]);

  async function connectVoice() {
    if (connectionStatus !== "connected") {
      await connect();
    }
    await connectVoiceTransport();
  }

  const value: VoiceChessSessionValue = {
    sessionId,
    boardState,
    conversationState,
    conversationMessages,
    toolCalls,
    connectionStatus,
    voiceConnectionStatus,
    voiceTransportAvailable,
    voiceTransportReason,
    errorMessage,
    voiceErrorMessage,
    microphonePermissionStatus,
    signalingApiUrl: signalingApiUrl ?? null,
    remoteAudioStream,
    selectedSquare,
    connect,
    disconnect,
    connectVoice,
    disconnectVoice,
    selectSquare: setSelectedSquare,
    sendCommand,
    requestMove(move: MoveIntent) {
      sendCommand(
        buildCommandEnvelope(sessionId, "board.request_move", {
          source: "user",
          move,
        }),
      );
    },
    navigate(ply: number | null) {
      sendCommand(
        buildCommandEnvelope(sessionId, "board.navigate", {
          mode: ply === null ? "live" : "review",
          ply,
        }),
      );
    },
    loadFen(fen: string) {
      sendCommand(
        buildCommandEnvelope(sessionId, "board.request_load_fen", {
          source: "user",
          fen,
        }),
      );
    },
    loadPgn(pgn: string, startPly: number | null = null) {
      sendCommand(
        buildCommandEnvelope(sessionId, "board.request_load_pgn", {
          source: "user",
          pgn,
          startPly,
        }),
      );
    },
    requestDemoPrompt(prompt: string) {
      sendCommand(
        buildCommandEnvelope(sessionId, "conversation.request_demo", {
          source: "user",
          prompt,
        }),
      );
    },
    resetBoard() {
      sendCommand(
        buildCommandEnvelope(sessionId, "board.request_reset", {
          source: "user",
        }),
      );
    },
  };

  return <VoiceChessContext.Provider value={value}>{children}</VoiceChessContext.Provider>;
}

function applyServerEvent(
  event: VoiceChessServerEvent,
  handlers: {
    setBoardState: Dispatch<SetStateAction<BoardState | null>>;
    setConversationState: Dispatch<SetStateAction<ConversationState>>;
    setConversationMessages: Dispatch<SetStateAction<ConversationMessage[]>>;
    setToolCalls: Dispatch<SetStateAction<ToolCallTrace[]>>;
    setErrorMessage: (value: string | null) => void;
    setSelectedSquare: (value: string | null) => void;
  },
) {
  const {
    setBoardState,
    setConversationState,
    setConversationMessages,
    setToolCalls,
    setErrorMessage,
    setSelectedSquare,
  } = handlers;

  switch (event.type) {
    case "session.ready":
      setErrorMessage(null);
      return;
    case "session.error":
      setErrorMessage(event.payload.message);
      return;
    case "board.state":
    case "board.reset":
      setBoardState(event.payload.board);
      setSelectedSquare(null);
      return;
    case "board.move_applied":
      setBoardState(event.payload.board);
      setSelectedSquare(null);
      return;
    case "board.annotation_set":
      setBoardState((current) =>
        current
          ? {
              ...current,
              annotations: event.payload.annotations,
            }
          : current,
      );
      return;
    case "board.highlight_set":
      setBoardState((current) =>
        current
          ? {
              ...current,
              highlights: event.payload.highlights,
            }
          : current,
      );
      return;
    case "voice.state":
      setConversationState(event.payload.state);
      return;
    case "conversation.message":
      setConversationMessages((current) => [...current, event.payload.message]);
      return;
    case "tool.call":
      setToolCalls((current) => [...current, event.payload.toolCall]);
      return;
    default:
      return;
  }
}
