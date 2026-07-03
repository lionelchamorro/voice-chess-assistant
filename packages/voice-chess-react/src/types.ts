import type {
  BoardState,
  ConversationMessage,
  ConversationState,
  ToolCallTrace,
  VoiceChessClientCommand,
} from "@voice-chess/core";
import type { ReactNode } from "react";

export type ConnectionStatus = "idle" | "connecting" | "connected" | "error";
export type VoiceConnectionStatus = ConnectionStatus | "requesting_media";
export type MicrophonePermissionStatus = "unknown" | "granted" | "denied";

export interface MoveIntent {
  from: string;
  to: string;
  promotion?: "queen" | "rook" | "bishop" | "knight" | null;
}

export interface BoardSquareState {
  square: string;
  piece: string | null;
  isLight: boolean;
  isSelected: boolean;
  isLegalTarget: boolean;
  isLastMove: boolean;
  highlightColor: string | null;
}

export interface VoiceChessProviderProps {
  boardSocketUrl: string;
  signalingApiUrl?: string;
  sessionId: string;
  autoConnect?: boolean;
  /**
   * ICE servers for the voice WebRTC peer connection. Defaults to a public
   * Google STUN server, matching the backend's default `stun_urls` setting.
   * Provide TURN servers here for clients behind symmetric NATs.
   */
  iceServers?: RTCIceServer[];
  children: ReactNode;
}

export interface VoiceChessSessionValue {
  sessionId: string;
  boardState: BoardState | null;
  conversationState: ConversationState;
  conversationMessages: ConversationMessage[];
  toolCalls: ToolCallTrace[];
  connectionStatus: ConnectionStatus;
  voiceConnectionStatus: VoiceConnectionStatus;
  voiceTransportAvailable: boolean;
  voiceTransportReason: string | null;
  errorMessage: string | null;
  voiceErrorMessage: string | null;
  microphonePermissionStatus: MicrophonePermissionStatus;
  signalingApiUrl: string | null;
  remoteAudioStream: MediaStream | null;
  selectedSquare: string | null;
  connect: () => Promise<void>;
  disconnect: () => void;
  connectVoice: () => Promise<void>;
  disconnectVoice: () => void;
  selectSquare: (square: string | null) => void;
  sendCommand: (command: VoiceChessClientCommand) => void;
  requestMove: (move: MoveIntent) => void;
  navigate: (ply: number | null) => void;
  loadFen: (fen: string) => void;
  loadPgn: (pgn: string, startPly?: number | null) => void;
  requestDemoPrompt: (prompt: string) => void;
  resetBoard: () => void;
}
