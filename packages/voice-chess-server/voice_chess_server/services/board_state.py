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
    variation_moves: list[chess.Move] = field(default_factory=list)
    variation_descriptors: list[MoveDescriptor] = field(default_factory=list)

    def reset(self) -> BoardState:
        """Reset to starting position."""

        self.root_fen = chess.STARTING_FEN
        self.pgn_text = None
        self.move_stack.clear()
        self.annotations.clear()
        self.highlights.clear()
        self.view_mode = "live"
        self.review_ply = None
        self._clear_variation()
        return self.snapshot()

    def apply_move(
        self,
        from_square: str | None = None,
        to_square: str | None = None,
        promotion: PromotionPiece | None = None,
        san: str | None = None,
    ) -> tuple[MoveDescriptor, BoardState]:
        """Apply a legal move in live mode, given coordinates or SAN."""

        if self.view_mode != "live":
            raise BoardCommandError(
                "review_mode_locked",
                "Cannot apply a move while the board is in review mode.",
            )

        board = self._live_board()
        move = self._resolve_move(board, from_square, to_square, promotion, san)

        descriptor = self._build_move_descriptor(board, move, len(self.move_stack) + 1)
        self.move_stack.append(move)
        self.view_mode = "live"
        self.review_ply = None
        self._clear_variation()
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
        self._clear_variation()
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
        self._clear_variation()
        if start_ply is None:
            self.view_mode = "live"
            self.review_ply = None
        else:
            self.navigate("review", start_ply)
        return self.snapshot()

    def undo_move(self) -> tuple[MoveDescriptor, BoardState]:
        """Undo the latest live move."""

        if self.view_mode != "live":
            raise BoardCommandError(
                "review_mode_locked",
                "Cannot undo a move while the board is in review mode.",
            )

        if not self.move_stack:
            raise BoardCommandError("no_moves_to_undo", "There is no move to undo.")

        history = self._move_history()
        last_move = history[-1]
        self.move_stack.pop()
        self.review_ply = None
        return last_move, self.snapshot()

    def set_annotations(self, annotations: list[BoardAnnotation]) -> BoardState:
        """Replace board annotations."""

        self.annotations = annotations
        return self.snapshot()

    def set_highlights(self, highlights: list[BoardHighlight]) -> BoardState:
        """Replace board highlights."""

        self.highlights = highlights
        return self.snapshot()

    def clear_highlights(self) -> BoardState:
        """Clear all highlights."""

        self.highlights = []
        return self.snapshot()

    def navigate(self, mode: BoardViewMode, ply: int | None) -> BoardState:
        """Move between live and review mode."""

        self._clear_variation()

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

    def step_review(self, offset: int) -> BoardState:
        """Step the reviewed game forward or backward by `offset` plies.

        Stepping past the final move returns the board to live mode.
        """

        if not self.move_stack:
            raise BoardCommandError("no_moves", "There are no recorded moves to review.")

        current = (
            self.review_ply
            if self.view_mode == "review" and self.review_ply is not None
            else len(self.move_stack)
        )
        target = current + offset
        if target < 0 or target > len(self.move_stack):
            raise BoardCommandError("invalid_ply", "Requested review ply is out of range.")

        self._clear_variation()
        if target == len(self.move_stack):
            self.view_mode = "live"
            self.review_ply = None
        else:
            self.view_mode = "review"
            self.review_ply = target
        return self.snapshot()

    def play_variation_move(
        self,
        from_square: str | None = None,
        to_square: str | None = None,
        promotion: PromotionPiece | None = None,
        san: str | None = None,
    ) -> tuple[MoveDescriptor, BoardState]:
        """Play a hypothetical sideline move on top of the reviewed position.

        The recorded game is untouched; `end_variation` returns to it.
        """

        if self.view_mode != "review":
            raise BoardCommandError(
                "variation_requires_review",
                "Sidelines can only be explored while reviewing a game. "
                "Use make_move to play on the live board.",
            )

        board = self._view_board()
        move = self._resolve_move(board, from_square, to_square, promotion, san)

        ply = (self.review_ply or 0) + len(self.variation_moves) + 1
        descriptor = self._build_move_descriptor(board, move, ply)
        self.variation_moves.append(move)
        self.variation_descriptors.append(descriptor)
        return descriptor, self.snapshot()

    def end_variation(self) -> BoardState:
        """Drop the current sideline and return to the reviewed position."""

        self._clear_variation()
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
            lastMove=self._visible_last_move(history),
            variation=[descriptor.san for descriptor in self.variation_descriptors],
            annotations=self.annotations,
            highlights=self.highlights,
            isCheck=board.is_check(),
            isCheckmate=board.is_checkmate(),
            isStalemate=board.is_stalemate(),
            isDraw=board.is_insufficient_material() or board.can_claim_draw(),
        )

    def _visible_last_move(self, history: list[MoveDescriptor]) -> MoveDescriptor | None:
        """The move that produced the position currently on screen."""

        if self.variation_descriptors:
            return self.variation_descriptors[-1]
        if self.view_mode == "review":
            if not self.review_ply:
                return None
            return history[self.review_ply - 1]
        return history[-1] if history else None

    def _clear_variation(self) -> None:
        self.variation_moves.clear()
        self.variation_descriptors.clear()

    def _resolve_move(
        self,
        board: chess.Board,
        from_square: str | None,
        to_square: str | None,
        promotion: PromotionPiece | None,
        san: str | None,
    ) -> chess.Move:
        """Resolve SAN or coordinate input into a legal move on `board`."""

        if san:
            try:
                return board.parse_san(san.strip())
            except ValueError as exc:
                raise BoardCommandError(
                    "illegal_move", f"'{san}' is not a legal move in this position."
                ) from exc

        if not from_square or not to_square:
            raise BoardCommandError(
                "missing_squares",
                "Provide from_square and to_square, or a SAN move.",
            )

        promotion_piece = PROMOTION_SYMBOL_BY_NAME.get(promotion) if promotion else None
        uci = from_square + to_square
        if promotion is not None:
            uci += PROMOTION_UCI_SUFFIX_BY_NAME[promotion]
        try:
            move = chess.Move.from_uci(uci)
        except ValueError as exc:
            raise BoardCommandError(
                "invalid_squares", f"'{from_square}' to '{to_square}' is not a valid move input."
            ) from exc
        if promotion_piece is not None:
            move.promotion = promotion_piece

        if move not in board.legal_moves:
            # A pawn reaching the last rank without an explicit promotion is a
            # common tool-call omission; default it to a queen.
            piece = board.piece_at(move.from_square)
            if (
                promotion is None
                and piece is not None
                and piece.piece_type == chess.PAWN
                and chess.square_rank(move.to_square) in (0, 7)
            ):
                promoted = chess.Move(move.from_square, move.to_square, promotion=chess.QUEEN)
                if promoted in board.legal_moves:
                    return promoted
            raise BoardCommandError("illegal_move", "The requested move is not legal.")
        return move

    def _base_board(self) -> chess.Board:
        return chess.Board(self.root_fen)

    def _live_board(self) -> chess.Board:
        board = self._base_board()
        for move in self.move_stack:
            board.push(move)
        return board

    def _view_board(self) -> chess.Board:
        board = self._base_board()
        moves = (
            self.move_stack if self.view_mode == "live" else self.move_stack[: self.review_ply or 0]
        )
        for move in moves:
            board.push(move)
        for move in self.variation_moves:
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
