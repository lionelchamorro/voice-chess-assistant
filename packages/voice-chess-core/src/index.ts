export const VOICE_CHESS_PROTOCOL_VERSION = "1.0.0" as const;

export type {
  BoardAnnotation,
  BoardHighlight,
  BoardNavigateCommand,
  BoardRequestLoadFenCommand,
  BoardRequestLoadPgnCommand,
  BoardRequestMoveCommand,
  BoardRequestResetCommand,
  BoardState,
  BoardStateEvent,
  BoardViewMode,
  Color,
  LegalMovesMap,
  MoveAppliedEvent,
  MoveDescriptor,
  PromotionPiece,
  SessionErrorEvent,
  SessionReadyEvent,
  VoiceChessClientCommand,
  VoiceChessEnvelope,
  VoiceChessServerEvent,
} from "./types";
