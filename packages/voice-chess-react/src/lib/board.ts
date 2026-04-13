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
    return "linear-gradient(180deg, #f7d774 0%, #e5b83d 100%)";
  }
  if (square.isLegalTarget) {
    return "linear-gradient(180deg, #c7f3b3 0%, #84cc16 100%)";
  }
  if (square.highlightColor === "green") {
    return "linear-gradient(180deg, #bbf7d0 0%, #4ade80 100%)";
  }
  if (square.highlightColor === "yellow") {
    return "linear-gradient(180deg, #fde68a 0%, #f59e0b 100%)";
  }
  if (square.highlightColor === "red") {
    return "linear-gradient(180deg, #fecaca 0%, #ef4444 100%)";
  }
  if (square.highlightColor === "blue") {
    return "linear-gradient(180deg, #bfdbfe 0%, #3b82f6 100%)";
  }
  if (square.isLastMove) {
    return "linear-gradient(180deg, #e9d5ff 0%, #c084fc 100%)";
  }
  return square.isLight ? "#f2dfc2" : "#b07a4f";
}
