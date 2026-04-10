import type { BoardState, VoiceChessClientCommand } from "@voice-chess/core";
import type { ReactNode } from "react";

export type ConnectionStatus = "idle" | "connecting" | "connected" | "error";

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
  sessionId: string;
  autoConnect?: boolean;
  children: ReactNode;
}

export interface VoiceChessSessionValue {
  sessionId: string;
  boardState: BoardState | null;
  connectionStatus: ConnectionStatus;
  errorMessage: string | null;
  selectedSquare: string | null;
  connect: () => Promise<void>;
  disconnect: () => void;
  selectSquare: (square: string | null) => void;
  sendCommand: (command: VoiceChessClientCommand) => void;
  requestMove: (move: MoveIntent) => void;
  navigate: (ply: number | null) => void;
  loadFen: (fen: string) => void;
  loadPgn: (pgn: string, startPly?: number | null) => void;
  resetBoard: () => void;
}
