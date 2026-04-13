export type ProtocolVersion = "1.0.0";
export type Color = "white" | "black";
export type BoardViewMode = "live" | "review";
export type CommandSource = "user" | "agent" | "system";
export type EventOrigin = "session-init" | "server-sync" | "user-command" | "agent-tool";
export type PromotionPiece = "queen" | "rook" | "bishop" | "knight";
export type ConversationState = "idle" | "listening" | "thinking" | "speaking";
export type ConversationMessageRole = "user" | "assistant" | "system";
export type ToolCallStatus = "started" | "completed";

export type LegalMovesMap = Record<string, string[]>;

export interface VoiceChessEnvelope<
  TType extends string,
  TPayload,
  TDirection extends "command" | "event",
> {
  protocolVersion: ProtocolVersion;
  direction: TDirection;
  type: TType;
  messageId: string;
  sessionId: string;
  timestamp: string;
  payload: TPayload;
}

export interface MoveDescriptor {
  ply: number;
  san: string;
  uci: string;
  from: string;
  to: string;
  fenAfter: string;
  color: Color;
  piece: string;
  capturedPiece?: string | null;
  promotion?: PromotionPiece | null;
}

export interface BoardAnnotation {
  id: string;
  kind: "comment" | "arrow" | "circle";
  color: "green" | "yellow" | "red" | "blue";
  from?: string;
  to?: string;
  square?: string;
  text?: string;
}

export interface BoardHighlight {
  id: string;
  squares: string[];
  color: "green" | "yellow" | "red" | "blue";
  label?: string;
}

export interface ConversationMessage {
  id: string;
  role: ConversationMessageRole;
  content: string;
  createdAt: string;
}

export interface ToolCallTrace {
  id: string;
  toolName: string;
  status: ToolCallStatus;
  summary: string;
  arguments?: Record<string, unknown> | null;
  createdAt: string;
}

export interface BoardState {
  fen: string;
  pgn?: string | null;
  orientation: Color;
  turn: Color;
  viewMode: BoardViewMode;
  reviewPly?: number | null;
  legalMoves: LegalMovesMap;
  moveHistory: MoveDescriptor[];
  lastMove?: MoveDescriptor | null;
  annotations: BoardAnnotation[];
  highlights: BoardHighlight[];
  isCheck: boolean;
  isCheckmate: boolean;
  isStalemate: boolean;
  isDraw: boolean;
}

export type SessionReadyEvent = VoiceChessEnvelope<
  "session.ready",
  {
    transport: "smallwebrtc";
    capabilities: {
      manualMoves: true;
      pgnNavigation: true;
      boardAnnotations: true;
      boardHighlights: true;
    };
  },
  "event"
>;

export type SessionErrorEvent = VoiceChessEnvelope<
  "session.error",
  {
    code: string;
    message: string;
    recoverable: boolean;
  },
  "event"
>;

export type BoardStateEvent = VoiceChessEnvelope<
  "board.state",
  {
    origin: EventOrigin;
    board: BoardState;
  },
  "event"
>;

export type MoveAppliedEvent = VoiceChessEnvelope<
  "board.move_applied",
  {
    origin: EventOrigin;
    move: MoveDescriptor;
    board: BoardState;
  },
  "event"
>;

export type AnnotationSetEvent = VoiceChessEnvelope<
  "board.annotation_set",
  {
    annotations: BoardAnnotation[];
  },
  "event"
>;

export type HighlightSetEvent = VoiceChessEnvelope<
  "board.highlight_set",
  {
    highlights: BoardHighlight[];
  },
  "event"
>;

export type BoardResetEvent = VoiceChessEnvelope<
  "board.reset",
  {
    origin: EventOrigin;
    board: BoardState;
  },
  "event"
>;

export type VoiceStateEvent = VoiceChessEnvelope<
  "voice.state",
  {
    state: ConversationState;
  },
  "event"
>;

export type ConversationMessageEvent = VoiceChessEnvelope<
  "conversation.message",
  {
    message: ConversationMessage;
  },
  "event"
>;

export type ToolCallEvent = VoiceChessEnvelope<
  "tool.call",
  {
    toolCall: ToolCallTrace;
  },
  "event"
>;

export type VoiceChessServerEvent =
  | SessionReadyEvent
  | SessionErrorEvent
  | BoardStateEvent
  | MoveAppliedEvent
  | AnnotationSetEvent
  | HighlightSetEvent
  | BoardResetEvent
  | VoiceStateEvent
  | ConversationMessageEvent
  | ToolCallEvent;

export type BoardRequestMoveCommand = VoiceChessEnvelope<
  "board.request_move",
  {
    source: CommandSource;
    move: {
      from: string;
      to: string;
      promotion?: PromotionPiece | null;
    };
  },
  "command"
>;

export type BoardNavigateCommand = VoiceChessEnvelope<
  "board.navigate",
  {
    mode: BoardViewMode;
    ply?: number | null;
  },
  "command"
>;

export type BoardRequestResetCommand = VoiceChessEnvelope<
  "board.request_reset",
  {
    source: CommandSource;
  },
  "command"
>;

export type BoardRequestLoadFenCommand = VoiceChessEnvelope<
  "board.request_load_fen",
  {
    source: CommandSource;
    fen: string;
  },
  "command"
>;

export type BoardRequestLoadPgnCommand = VoiceChessEnvelope<
  "board.request_load_pgn",
  {
    source: CommandSource;
    pgn: string;
    startPly?: number | null;
  },
  "command"
>;

export type ConversationRequestDemoCommand = VoiceChessEnvelope<
  "conversation.request_demo",
  {
    source: CommandSource;
    prompt: string;
  },
  "command"
>;

export type VoiceChessClientCommand =
  | BoardRequestMoveCommand
  | BoardNavigateCommand
  | BoardRequestResetCommand
  | BoardRequestLoadFenCommand
  | BoardRequestLoadPgnCommand
  | ConversationRequestDemoCommand;
