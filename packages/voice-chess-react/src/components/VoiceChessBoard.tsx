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
        padding: 14,
        gap: 0,
        background: "linear-gradient(145deg, #8b5e34 0%, #6f4726 100%)",
        border: "1px solid #5f3a1f",
        borderRadius: 18,
        boxShadow: "inset 0 1px 0 rgba(255, 255, 255, 0.15), 0 18px 40px rgba(15, 23, 42, 0.16)",
      }}
    >
      {squares.map((square, index) => {
        const isBottomRank = Math.floor(index / 8) === 7;
        const isLeftFile = index % 8 === 0;
        return (
          <button
            key={square.square}
            type="button"
            aria-label={`Square ${square.square}${square.piece ? ` occupied by ${square.piece}` : ""}`}
            onClick={() => {
              if (!interactive) {
                return;
              }
              handleSquareClick(square, boardState, session.selectedSquare, promotionPiece, session);
            }}
            style={{
              aspectRatio: "1 / 1",
              border: 0,
              borderRadius: 0,
              padding: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              cursor: interactive ? "pointer" : "default",
              background: resolveSquareBackground(square),
              color: square.piece && square.piece === square.piece.toUpperCase() ? "#f8fafc" : "#0f172a",
              fontSize: "clamp(2.2rem, 4vw, 3.15rem)",
              lineHeight: 1,
              position: "relative",
              textShadow:
                square.piece && square.piece === square.piece.toUpperCase()
                  ? "0 1px 0 rgba(15, 23, 42, 0.7)"
                  : "0 1px 0 rgba(248, 250, 252, 0.45)",
            }}
          >
            <span>{square.piece ? PIECE_TO_SYMBOL[square.piece] : ""}</span>
            {isLeftFile ? (
              <span
                style={{
                  position: "absolute",
                  top: 6,
                  left: 6,
                  fontSize: "0.68rem",
                  fontWeight: 700,
                  opacity: 0.68,
                  color: square.isLight ? "#6b4323" : "#f8fafc",
                }}
              >
                {square.square[1]}
              </span>
            ) : null}
            {isBottomRank ? (
              <span
                style={{
                  position: "absolute",
                  right: 6,
                  bottom: 6,
                  fontSize: "0.68rem",
                  fontWeight: 700,
                  opacity: 0.68,
                  color: square.isLight ? "#6b4323" : "#f8fafc",
                }}
              >
                {square.square[0]}
              </span>
            ) : null}
          </button>
        );
      })}
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
