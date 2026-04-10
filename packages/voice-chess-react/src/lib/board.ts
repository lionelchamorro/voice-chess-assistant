import type { BoardState } from "@voice-chess/core";

import type { BoardSquareState } from "../types";

export function buildSquareState(boardState: BoardState, selectedSquare: string | null): BoardSquareState[] {
  const [placement = ""] = boardState.fen.split(" ");
  const rows = placement.split("/");
  const linearSquares: Array<{ square: string; piece: string | null }> = [];
  const files = boardState.orientation === "white" ? "abcdefgh" : "hgfedcba";
  const ranks = boardState.orientation === "white" ? [8, 7, 6, 5, 4, 3, 2, 1] : [1, 2, 3, 4, 5, 6, 7, 8];

  for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
    const row = rows[rowIndex]!;
    const rank = ranks[rowIndex]!;
    let fileIndex = 0;
    for (const token of row) {
      const parsed = Number(token);
      if (!Number.isNaN(parsed)) {
        for (let empty = 0; empty < parsed; empty += 1) {
          linearSquares.push({
            square: `${files[fileIndex]}${rank}`,
            piece: null,
          });
          fileIndex += 1;
        }
        continue;
      }
      linearSquares.push({
        square: `${files[fileIndex]}${rank}`,
        piece: token,
      });
      fileIndex += 1;
    }
  }

  const legalTargets = selectedSquare ? new Set(boardState.legalMoves[selectedSquare] ?? []) : new Set<string>();
  const lastMoveSquares = new Set(
    boardState.lastMove ? [boardState.lastMove.from, boardState.lastMove.to] : [],
  );
  const highlightBySquare = new Map<string, string>();
  for (const highlight of boardState.highlights) {
    for (const square of highlight.squares) {
      highlightBySquare.set(square, highlight.color);
    }
  }

  return linearSquares.map((squareState, index) => ({
    ...squareState,
    isLight: (Math.floor(index / 8) + (index % 8)) % 2 === 0,
    isSelected: squareState.square === selectedSquare,
    isLegalTarget: legalTargets.has(squareState.square),
    isLastMove: lastMoveSquares.has(squareState.square),
    highlightColor: highlightBySquare.get(squareState.square) ?? null,
  }));
}

export function resolveSquareBackground(square: BoardSquareState): string {
  if (square.isSelected) {
    return "#fde68a";
  }
  if (square.isLegalTarget) {
    return "#bbf7d0";
  }
  if (square.highlightColor === "green") {
    return "#bbf7d0";
  }
  if (square.highlightColor === "yellow") {
    return "#fde68a";
  }
  if (square.highlightColor === "red") {
    return "#fecaca";
  }
  if (square.highlightColor === "blue") {
    return "#bfdbfe";
  }
  if (square.isLastMove) {
    return "#e9d5ff";
  }
  return square.isLight ? "#f8fafc" : "#dbe4f0";
}
