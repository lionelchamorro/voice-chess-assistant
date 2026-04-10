"""Board session state and chess operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO

import chess
import chess.pgn

from voice_chess_server.schemas.protocol import (
    BoardAnnotation,
    BoardHighlight,
    BoardState,
    BoardViewMode,
    MoveDescriptor,
    PromotionPiece,
)

PIECE_NAME_BY_TYPE = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}

PROMOTION_SYMBOL_BY_NAME = {
    "queen": chess.QUEEN,
    "rook": chess.ROOK,
    "bishop": chess.BISHOP,
    "knight": chess.KNIGHT,
}

PROMOTION_UCI_SUFFIX_BY_NAME = {
    "queen": "q",
    "rook": "r",
    "bishop": "b",
    "knight": "n",
}


class BoardCommandError(ValueError):
    """Raised when a board command cannot be applied."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class BoardSessionState:
    """Canonical board session state."""

    session_id: str
    orientation: str = "white"
    root_fen: str = chess.STARTING_FEN
    pgn_text: str | None = None
    move_stack: list[chess.Move] = field(default_factory=list)
    annotations: list[BoardAnnotation] = field(default_factory=list)
    highlights: list[BoardHighlight] = field(default_factory=list)
    view_mode: BoardViewMode = "live"
    review_ply: int | None = None

    def reset(self) -> BoardState:
        """Reset to starting position."""

        self.root_fen = chess.STARTING_FEN
        self.pgn_text = None
        self.move_stack.clear()
        self.annotations.clear()
        self.highlights.clear()
        self.view_mode = "live"
        self.review_ply = None
        return self.snapshot()

    def apply_move(
        self,
        from_square: str,
        to_square: str,
        promotion: PromotionPiece | None = None,
    ) -> tuple[MoveDescriptor, BoardState]:
        """Apply a legal move in live mode."""

        if self.view_mode != "live":
            raise BoardCommandError(
                "review_mode_locked",
                "Cannot apply a move while the board is in review mode.",
            )

        board = self._live_board()
        promotion_piece = PROMOTION_SYMBOL_BY_NAME.get(promotion) if promotion else None
        uci = from_square + to_square
        if promotion is not None:
            uci += PROMOTION_UCI_SUFFIX_BY_NAME[promotion]
        move = chess.Move.from_uci(uci)
        if promotion_piece is not None:
            move.promotion = promotion_piece

        if move not in board.legal_moves:
            raise BoardCommandError("illegal_move", "The requested move is not legal.")

        descriptor = self._build_move_descriptor(board, move, len(self.move_stack) + 1)
        self.move_stack.append(move)
        self.view_mode = "live"
        self.review_ply = None
        return descriptor, self.snapshot()

    def load_fen(self, fen: str) -> BoardState:
        """Load a new board from FEN."""

        board = chess.Board(fen)
        self.root_fen = board.fen()
        self.pgn_text = None
        self.move_stack.clear()
        self.annotations.clear()
        self.highlights.clear()
        self.view_mode = "live"
        self.review_ply = None
        return self.snapshot()

    def load_pgn(self, pgn: str, start_ply: int | None = None) -> BoardState:
        """Load PGN and move to live or requested ply."""

        game = chess.pgn.read_game(StringIO(pgn))
        if game is None:
            raise BoardCommandError("invalid_pgn", "Could not parse PGN content.")

        board = game.board()
        self.root_fen = board.fen()
        self.move_stack = list(game.mainline_moves())
        self.pgn_text = pgn.strip()
        self.annotations.clear()
        self.highlights.clear()
        if start_ply is None:
            self.view_mode = "live"
            self.review_ply = None
        else:
            self.navigate("review", start_ply)
        return self.snapshot()

    def set_annotations(self, annotations: list[BoardAnnotation]) -> BoardState:
        """Replace board annotations."""

        self.annotations = annotations
        return self.snapshot()

    def set_highlights(self, highlights: list[BoardHighlight]) -> BoardState:
        """Replace board highlights."""

        self.highlights = highlights
        return self.snapshot()

    def navigate(self, mode: BoardViewMode, ply: int | None) -> BoardState:
        """Move between live and review mode."""

        if mode == "live":
            self.view_mode = "live"
            self.review_ply = None
            return self.snapshot()

        if ply is None:
            raise BoardCommandError("missing_ply", "A review ply is required in review mode.")

        if ply < 0 or ply > len(self.move_stack):
            raise BoardCommandError("invalid_ply", "Requested review ply is out of range.")

        self.view_mode = "review"
        self.review_ply = ply
        return self.snapshot()

    def snapshot(self) -> BoardState:
        """Create canonical board state for the current view."""

        board = self._view_board()
        history = self._move_history()
        return BoardState(
            fen=board.fen(),
            pgn=self._current_pgn(),
            orientation=self.orientation,
            turn="white" if board.turn == chess.WHITE else "black",
            viewMode=self.view_mode,
            reviewPly=self.review_ply,
            legalMoves=self._legal_moves_map(board),
            moveHistory=history,
            lastMove=history[-1] if history else None,
            annotations=self.annotations,
            highlights=self.highlights,
            isCheck=board.is_check(),
            isCheckmate=board.is_checkmate(),
            isStalemate=board.is_stalemate(),
            isDraw=board.is_insufficient_material() or board.can_claim_draw(),
        )

    def _base_board(self) -> chess.Board:
        return chess.Board(self.root_fen)

    def _live_board(self) -> chess.Board:
        board = self._base_board()
        for move in self.move_stack:
            board.push(move)
        return board

    def _view_board(self) -> chess.Board:
        board = self._base_board()
        moves = self.move_stack if self.view_mode == "live" else self.move_stack[: self.review_ply or 0]
        for move in moves:
            board.push(move)
        return board

    def _move_history(self) -> list[MoveDescriptor]:
        board = self._base_board()
        descriptors: list[MoveDescriptor] = []
        for ply, move in enumerate(self.move_stack, start=1):
            descriptor = self._build_move_descriptor(board, move, ply)
            descriptors.append(descriptor)
        return descriptors

    def _build_move_descriptor(
        self,
        board: chess.Board,
        move: chess.Move,
        ply: int,
    ) -> MoveDescriptor:
        piece = board.piece_at(move.from_square)
        captured_piece = board.piece_at(move.to_square)
        san = board.san(move)
        board.push(move)
        descriptor = MoveDescriptor(
            ply=ply,
            san=san,
            uci=move.uci(),
            **{
                "from": chess.square_name(move.from_square),
                "to": chess.square_name(move.to_square),
                "fenAfter": board.fen(),
                "color": "white" if not board.turn else "black",
                "piece": PIECE_NAME_BY_TYPE[piece.piece_type] if piece else "unknown",
                "capturedPiece": PIECE_NAME_BY_TYPE[captured_piece.piece_type]
                if captured_piece
                else None,
                "promotion": self._promotion_name(move.promotion),
            },
        )
        return descriptor

    def _promotion_name(self, promotion: int | None) -> PromotionPiece | None:
        if promotion is None:
            return None
        for name, piece in PROMOTION_SYMBOL_BY_NAME.items():
            if piece == promotion:
                return name
        return None

    def _current_pgn(self) -> str | None:
        if self.pgn_text:
            return self.pgn_text
        if not self.move_stack:
            return None
        board = self._base_board()
        game = chess.pgn.Game()
        node = game
        for move in self.move_stack:
            node = node.add_variation(move)
            board.push(move)
        exporter = chess.pgn.StringExporter(headers=False, variations=False, comments=False)
        return game.accept(exporter).strip() or None

    def _legal_moves_map(self, board: chess.Board) -> dict[str, list[str]]:
        moves: dict[str, list[str]] = {}
        for move in board.legal_moves:
            from_square = chess.square_name(move.from_square)
            moves.setdefault(from_square, []).append(chess.square_name(move.to_square))
        return moves
