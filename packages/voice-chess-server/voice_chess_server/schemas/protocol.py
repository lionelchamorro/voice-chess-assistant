"""Pydantic protocol models for board commands and events."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


ProtocolVersion = Literal["1.0.0"]
Color = Literal["white", "black"]
BoardViewMode = Literal["live", "review"]
CommandSource = Literal["user", "agent", "system"]
EventOrigin = Literal["session-init", "server-sync", "user-command", "agent-tool"]
PromotionPiece = Literal["queen", "rook", "bishop", "knight"]
ConversationState = Literal["idle", "listening", "thinking", "speaking"]
ConversationMessageRole = Literal["user", "assistant", "system"]
ToolCallStatus = Literal["started", "completed"]


class EnvelopeBase(BaseModel):
    """Common envelope metadata."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    protocol_version: ProtocolVersion = Field(default="1.0.0", alias="protocolVersion")
    message_id: str = Field(alias="messageId", min_length=1)
    session_id: str = Field(alias="sessionId", min_length=1)
    timestamp: str = Field(min_length=1)


class CommandEnvelopeBase(EnvelopeBase):
    """Shared fields for client commands."""

    direction: Literal["command"] = "command"


class EventEnvelopeBase(EnvelopeBase):
    """Shared fields for server events."""

    direction: Literal["event"] = "event"


class MoveRequestPayload(BaseModel):
    """Move request payload."""

    model_config = ConfigDict(extra="forbid")

    source: CommandSource
    move: dict[str, str | None]


class BoardRequestMoveCommand(CommandEnvelopeBase):
    """Client request to make a move."""

    type: Literal["board.request_move"] = "board.request_move"
    payload: MoveRequestPayload


class NavigatePayload(BaseModel):
    """Board navigation payload."""

    model_config = ConfigDict(extra="forbid")

    mode: BoardViewMode
    ply: int | None = Field(default=None, ge=0)


class BoardNavigateCommand(CommandEnvelopeBase):
    """Client request to navigate PGN history."""

    type: Literal["board.navigate"] = "board.navigate"
    payload: NavigatePayload


class ResetPayload(BaseModel):
    """Board reset payload."""

    model_config = ConfigDict(extra="forbid")

    source: CommandSource


class BoardRequestResetCommand(CommandEnvelopeBase):
    """Client request to reset the board."""

    type: Literal["board.request_reset"] = "board.request_reset"
    payload: ResetPayload


class LoadFenPayload(BaseModel):
    """Load FEN payload."""

    model_config = ConfigDict(extra="forbid")

    source: CommandSource
    fen: str = Field(min_length=1)


class BoardRequestLoadFenCommand(CommandEnvelopeBase):
    """Client request to load a FEN position."""

    type: Literal["board.request_load_fen"] = "board.request_load_fen"
    payload: LoadFenPayload


class LoadPgnPayload(BaseModel):
    """Load PGN payload."""

    model_config = ConfigDict(extra="forbid")

    source: CommandSource
    pgn: str = Field(min_length=1)
    start_ply: int | None = Field(default=None, alias="startPly", ge=0)


class BoardRequestLoadPgnCommand(CommandEnvelopeBase):
    """Client request to load PGN content."""

    type: Literal["board.request_load_pgn"] = "board.request_load_pgn"
    payload: LoadPgnPayload


class ConversationRequestDemoPayload(BaseModel):
    """Demo conversation request payload."""

    model_config = ConfigDict(extra="forbid")

    source: CommandSource
    prompt: str = Field(min_length=1)


class ConversationRequestDemoCommand(CommandEnvelopeBase):
    """Client request to simulate a voice turn for demo and tests."""

    type: Literal["conversation.request_demo"] = "conversation.request_demo"
    payload: ConversationRequestDemoPayload


VoiceChessClientCommand = Annotated[
    BoardRequestMoveCommand
    | BoardNavigateCommand
    | BoardRequestResetCommand
    | BoardRequestLoadFenCommand
    | BoardRequestLoadPgnCommand
    | ConversationRequestDemoCommand,
    Field(discriminator="type"),
]


class BoardAnnotation(BaseModel):
    """Board annotation."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["comment", "arrow", "circle"]
    color: Literal["green", "yellow", "red", "blue"]
    from_square: str | None = Field(default=None, alias="from")
    to_square: str | None = Field(default=None, alias="to")
    square: str | None = None
    text: str | None = None


class BoardHighlight(BaseModel):
    """Board highlight."""

    model_config = ConfigDict(extra="forbid")

    id: str
    squares: list[str]
    color: Literal["green", "yellow", "red", "blue"]
    label: str | None = None


class MoveDescriptor(BaseModel):
    """Normalized move descriptor."""

    model_config = ConfigDict(extra="forbid")

    ply: int = Field(ge=1)
    san: str
    uci: str
    from_square: str = Field(alias="from")
    to_square: str = Field(alias="to")
    fen_after: str = Field(alias="fenAfter")
    color: Color
    piece: str
    captured_piece: str | None = Field(default=None, alias="capturedPiece")
    promotion: PromotionPiece | None = None


class BoardState(BaseModel):
    """Canonical board state."""

    model_config = ConfigDict(extra="forbid")

    fen: str
    pgn: str | None = None
    orientation: Color
    turn: Color
    view_mode: BoardViewMode = Field(alias="viewMode")
    review_ply: int | None = Field(default=None, alias="reviewPly", ge=0)
    legal_moves: dict[str, list[str]] = Field(alias="legalMoves")
    move_history: list[MoveDescriptor] = Field(alias="moveHistory")
    last_move: MoveDescriptor | None = Field(default=None, alias="lastMove")
    variation: list[str] = Field(default_factory=list)
    annotations: list[BoardAnnotation]
    highlights: list[BoardHighlight]
    is_check: bool = Field(alias="isCheck")
    is_checkmate: bool = Field(alias="isCheckmate")
    is_stalemate: bool = Field(alias="isStalemate")
    is_draw: bool = Field(alias="isDraw")


class ConversationMessage(BaseModel):
    """Conversation message payload."""

    model_config = ConfigDict(extra="forbid")

    id: str
    role: ConversationMessageRole
    content: str
    created_at: str = Field(alias="createdAt")


class ToolCallTrace(BaseModel):
    """Trace event for a tool invoked by the assistant."""

    model_config = ConfigDict(extra="forbid")

    id: str
    tool_name: str = Field(alias="toolName")
    status: ToolCallStatus
    summary: str
    arguments: dict[str, object] | None = None
    created_at: str = Field(alias="createdAt")


class SessionReadyPayload(BaseModel):
    """Ready payload."""

    model_config = ConfigDict(extra="forbid")

    transport: Literal["smallwebrtc"] = "smallwebrtc"
    capabilities: dict[str, bool]


class SessionReadyEvent(EventEnvelopeBase):
    """Ready event."""

    type: Literal["session.ready"] = "session.ready"
    payload: SessionReadyPayload


class SessionErrorPayload(BaseModel):
    """Error payload."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    recoverable: bool


class SessionErrorEvent(EventEnvelopeBase):
    """Error event."""

    type: Literal["session.error"] = "session.error"
    payload: SessionErrorPayload


class BoardStatePayload(BaseModel):
    """Board state payload."""

    model_config = ConfigDict(extra="forbid")

    origin: EventOrigin
    board: BoardState


class BoardStateEvent(EventEnvelopeBase):
    """Board state event."""

    type: Literal["board.state"] = "board.state"
    payload: BoardStatePayload


class MoveAppliedPayload(BaseModel):
    """Move applied payload."""

    model_config = ConfigDict(extra="forbid")

    origin: EventOrigin
    move: MoveDescriptor
    board: BoardState


class MoveAppliedEvent(EventEnvelopeBase):
    """Move applied event."""

    type: Literal["board.move_applied"] = "board.move_applied"
    payload: MoveAppliedPayload


class AnnotationSetPayload(BaseModel):
    """Annotation payload."""

    model_config = ConfigDict(extra="forbid")

    annotations: list[BoardAnnotation]


class AnnotationSetEvent(EventEnvelopeBase):
    """Annotation set event."""

    type: Literal["board.annotation_set"] = "board.annotation_set"
    payload: AnnotationSetPayload


class HighlightSetPayload(BaseModel):
    """Highlight payload."""

    model_config = ConfigDict(extra="forbid")

    highlights: list[BoardHighlight]


class HighlightSetEvent(EventEnvelopeBase):
    """Highlight set event."""

    type: Literal["board.highlight_set"] = "board.highlight_set"
    payload: HighlightSetPayload


class BoardResetPayload(BaseModel):
    """Reset payload."""

    model_config = ConfigDict(extra="forbid")

    origin: EventOrigin
    board: BoardState


class BoardResetEvent(EventEnvelopeBase):
    """Reset event."""

    type: Literal["board.reset"] = "board.reset"
    payload: BoardResetPayload


class VoiceStatePayload(BaseModel):
    """Conversation state payload."""

    model_config = ConfigDict(extra="forbid")

    state: ConversationState


class VoiceStateEvent(EventEnvelopeBase):
    """Conversation state event."""

    type: Literal["voice.state"] = "voice.state"
    payload: VoiceStatePayload


class ConversationMessagePayload(BaseModel):
    """Conversation message event payload."""

    model_config = ConfigDict(extra="forbid")

    message: ConversationMessage


class ConversationMessageEvent(EventEnvelopeBase):
    """Conversation message event."""

    type: Literal["conversation.message"] = "conversation.message"
    payload: ConversationMessagePayload


class ToolCallPayload(BaseModel):
    """Assistant tool call event payload."""

    model_config = ConfigDict(extra="forbid")

    tool_call: ToolCallTrace = Field(alias="toolCall")


class ToolCallEvent(EventEnvelopeBase):
    """Assistant tool call event."""

    type: Literal["tool.call"] = "tool.call"
    payload: ToolCallPayload
