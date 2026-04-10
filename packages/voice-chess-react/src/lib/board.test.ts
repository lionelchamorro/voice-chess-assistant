import { describe, expect, it } from "vitest";

import type { BoardState } from "@voice-chess/core";

import { buildSquareState, resolveSquareBackground } from "./board";

const SAMPLE_BOARD_STATE: BoardState = {
  fen: "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
  pgn: "1. e4",
  orientation: "white",
  turn: "black",
  viewMode: "live",
  reviewPly: null,
  legalMoves: {
    a7: ["a6", "a5"],
    e7: ["e6", "e5"],
  },
  moveHistory: [
    {
      ply: 1,
      san: "e4",
      uci: "e2e4",
      from: "e2",
      to: "e4",
      fenAfter: "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
      color: "white",
      piece: "pawn",
      capturedPiece: null,
      promotion: null,
    },
  ],
  lastMove: {
    ply: 1,
    san: "e4",
    uci: "e2e4",
    from: "e2",
    to: "e4",
    fenAfter: "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
    color: "white",
    piece: "pawn",
    capturedPiece: null,
    promotion: null,
  },
  annotations: [],
  highlights: [
    {
      id: "highlight_1",
      squares: ["e4"],
      color: "green",
      label: "center control",
    },
  ],
  isCheck: false,
  isCheckmate: false,
  isStalemate: false,
  isDraw: false,
};

describe("buildSquareState", () => {
  it("maps FEN and last move metadata into square state", () => {
    const squares = buildSquareState(SAMPLE_BOARD_STATE, "e7");
    const e4 = squares.find((square) => square.square === "e4");
    const e7 = squares.find((square) => square.square === "e7");

    expect(squares).toHaveLength(64);
    expect(e4?.piece).toBe("P");
    expect(e4?.isLastMove).toBe(true);
    expect(e4?.highlightColor).toBe("green");
    expect(e7?.isSelected).toBe(true);
    expect(e7?.isLegalTarget).toBe(false);
  });

  it("marks legal targets for the selected square", () => {
    const squares = buildSquareState(SAMPLE_BOARD_STATE, "e7");
    const e5 = squares.find((square) => square.square === "e5");
    expect(e5?.isLegalTarget).toBe(true);
    expect(resolveSquareBackground(e5!)).toBe("#bbf7d0");
  });
});
