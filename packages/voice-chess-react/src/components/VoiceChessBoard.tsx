import type { BoardState } from "@voice-chess/core";
import { useState } from "react";

import { useVoiceChessSession } from "../hooks/useVoiceChessSession";
import type { BoardSquareState } from "../types";
import { buildSquareState, resolveSquareBackground } from "../lib/board";

const PIECE_TO_SYMBOL: Record<string, string> = {
  P: "♙",
  N: "♘",
  B: "♗",
  R: "♖",
  Q: "♕",
  K: "♔",
  p: "♟",
  n: "♞",
  b: "♝",
  r: "♜",
  q: "♛",
  k: "♚",
};

interface VoiceChessBoardProps {
  className?: string;
  interactive?: boolean;
}

export function VoiceChessBoard({
  className,
  interactive = true,
}: VoiceChessBoardProps) {
  const session = useVoiceChessSession();
  const [promotionPiece] = useState<"queen" | "rook" | "bishop" | "knight" | null>("queen");

  if (!session.boardState) {
    return <div className={className}>Waiting for board state...</div>;
  }

  const boardState = session.boardState;
  const squares = buildSquareState(boardState, session.selectedSquare);

  return (
    <div
      className={className}
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(8, minmax(0, 1fr))",
        border: "1px solid #d0d4db",
        borderRadius: 16,
        overflow: "hidden",
      }}
    >
      {squares.map((square) => (
        <button
          key={square.square}
          type="button"
          onClick={() => {
            if (!interactive) {
              return;
            }
            handleSquareClick(square, boardState, session.selectedSquare, promotionPiece, session);
          }}
          style={{
            aspectRatio: "1 / 1",
            border: 0,
            cursor: interactive ? "pointer" : "default",
            background: resolveSquareBackground(square),
            color: square.piece && square.piece === square.piece.toUpperCase() ? "#111827" : "#0f172a",
            fontSize: "2rem",
            position: "relative",
          }}
        >
          <span>{square.piece ? PIECE_TO_SYMBOL[square.piece] : ""}</span>
          <span
            style={{
              position: "absolute",
              bottom: 4,
              left: 6,
              fontSize: "0.7rem",
              opacity: 0.45,
            }}
          >
            {square.square}
          </span>
        </button>
      ))}
    </div>
  );
}

function handleSquareClick(
  square: BoardSquareState,
  boardState: BoardState,
  selectedSquare: string | null,
  promotion: "queen" | "rook" | "bishop" | "knight" | null,
  session: ReturnType<typeof useVoiceChessSession>,
) {
  const legalTargets = selectedSquare ? boardState.legalMoves[selectedSquare] ?? [] : [];

  if (selectedSquare && legalTargets.includes(square.square)) {
    session.requestMove({
      from: selectedSquare,
      to: square.square,
      promotion,
    });
    return;
  }

  if (boardState.legalMoves[square.square]?.length) {
    session.selectSquare(square.square);
    return;
  }

  session.selectSquare(null);
}
