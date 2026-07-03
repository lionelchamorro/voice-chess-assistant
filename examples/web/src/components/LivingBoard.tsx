import type { BoardState } from "@voice-chess/core";
import { useEffect, useMemo, useRef } from "react";

import { useVoiceChessSession } from "@voice-chess/react";

const GLYPH: Record<string, string> = {
  p: "♟",
  n: "♞",
  b: "♝",
  r: "♜",
  q: "♛",
  k: "♚",
};

const FILES = "abcdefgh";

interface TrackedPiece {
  id: string;
  code: string;
  square: string;
}

function parsePlacement(fen: string): Map<string, string> {
  const [placement = ""] = fen.split(" ");
  const map = new Map<string, string>();
  const rows = placement.split("/");
  for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
    const rank = 8 - rowIndex;
    let file = 0;
    for (const token of rows[rowIndex] ?? "") {
      const emptyCount = Number(token);
      if (!Number.isNaN(emptyCount)) {
        file += emptyCount;
        continue;
      }
      map.set(`${FILES[file]}${rank}`, token);
      file += 1;
    }
  }
  return map;
}

function squareDistance(a: string, b: string): number {
  return (
    Math.abs(a.charCodeAt(0) - b.charCodeAt(0)) + Math.abs(Number(a[1]) - Number(b[1]))
  );
}

/**
 * Carry stable piece identities across board states so pieces glide to their
 * new square instead of teleporting. `lastMove` resolves the moved piece
 * (including castling's rook); remaining pieces match by square, then by
 * nearest same-code piece, which also animates undos and small navigations.
 */
function reconcilePieces(
  prev: TrackedPiece[],
  board: BoardState,
  nextId: { current: number },
): TrackedPiece[] {
  const placement = parsePlacement(board.fen);
  const prevBySquare = new Map(prev.map((piece) => [piece.square, piece]));
  const consumed = new Set<string>();
  const assigned = new Set<string>();
  const next: TrackedPiece[] = [];

  const takeFrom = (square: string): TrackedPiece | null => {
    const candidate = prevBySquare.get(square);
    return candidate && !consumed.has(candidate.id) ? candidate : null;
  };
  const place = (square: string, piece: TrackedPiece | null, code: string) => {
    if (piece) {
      consumed.add(piece.id);
      next.push({ id: piece.id, code, square });
    } else {
      next.push({ id: `p${nextId.current++}`, code, square });
    }
    assigned.add(square);
  };

  const lastMove = board.lastMove;
  if (lastMove && placement.has(lastMove.to) && !assigned.has(lastMove.to)) {
    const mover = takeFrom(lastMove.from);
    if (mover) {
      place(lastMove.to, mover, placement.get(lastMove.to)!);
      if (mover.code.toLowerCase() === "k") {
        const fileDelta = lastMove.to.charCodeAt(0) - lastMove.from.charCodeAt(0);
        if (Math.abs(fileDelta) === 2) {
          const rank = lastMove.from[1];
          const rookFrom = `${fileDelta > 0 ? "h" : "a"}${rank}`;
          const rookTo = `${fileDelta > 0 ? "f" : "d"}${rank}`;
          const rook = takeFrom(rookFrom);
          if (rook && placement.has(rookTo) && !assigned.has(rookTo)) {
            place(rookTo, rook, placement.get(rookTo)!);
          }
        }
      }
    }
  }

  for (const [square, code] of placement) {
    if (assigned.has(square)) {
      continue;
    }
    const stay = prevBySquare.get(square);
    if (stay && !consumed.has(stay.id) && stay.code === code) {
      place(square, stay, code);
    }
  }

  for (const [square, code] of placement) {
    if (assigned.has(square)) {
      continue;
    }
    let best: TrackedPiece | null = null;
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const candidate of prev) {
      if (consumed.has(candidate.id) || candidate.code !== code) {
        continue;
      }
      const distance = squareDistance(candidate.square, square);
      if (distance < bestDistance) {
        best = candidate;
        bestDistance = distance;
      }
    }
    place(square, best, code);
  }

  return next;
}

function findKingSquare(board: BoardState): string | null {
  const kingCode = board.turn === "white" ? "K" : "k";
  for (const [square, code] of parsePlacement(board.fen)) {
    if (code === kingCode) {
      return square;
    }
  }
  return null;
}

export function LivingBoard() {
  const session = useVoiceChessSession();
  const board = session.boardState;
  const prevPiecesRef = useRef<TrackedPiece[]>([]);
  const nextIdRef = useRef(1);

  const pieces = useMemo(
    () => (board ? reconcilePieces(prevPiecesRef.current, board, nextIdRef) : []),
    [board],
  );

  useEffect(() => {
    prevPiecesRef.current = pieces;
  }, [pieces]);

  if (!board) {
    return (
      <div className="board-shell" data-voice="idle">
        <div className="board-empty">
          <span className="board-empty-glyph" aria-hidden="true">
            ♞
          </span>
          <p>The board is waiting.</p>
          <p className="board-empty-hint">Connect the session to set the pieces.</p>
        </div>
      </div>
    );
  }

  const whiteSide = board.orientation === "white";
  const squareX = (square: string) =>
    whiteSide ? square.charCodeAt(0) - 97 : 104 - square.charCodeAt(0);
  const squareY = (square: string) => (whiteSide ? 8 - Number(square[1]) : Number(square[1]) - 1);

  const selected = session.selectedSquare;
  const legalTargets = new Set(selected ? (board.legalMoves[selected] ?? []) : []);
  const occupied = parsePlacement(board.fen);
  const lastMoveSquares = new Set(
    board.lastMove ? [board.lastMove.from, board.lastMove.to] : [],
  );
  const highlightBySquare = new Map<string, string>();
  for (const highlight of board.highlights) {
    for (const square of highlight.squares) {
      highlightBySquare.set(square, highlight.color);
    }
  }
  const checkSquare = board.isCheck ? findKingSquare(board) : null;

  const handleSquareClick = (square: string) => {
    if (selected && legalTargets.has(square)) {
      const movingPiece = occupied.get(selected);
      const targetRank = square[1];
      const promotes =
        movingPiece?.toLowerCase() === "p" && (targetRank === "8" || targetRank === "1");
      session.requestMove({
        from: selected,
        to: square,
        promotion: promotes ? "queen" : null,
      });
      return;
    }
    if (board.legalMoves[square]?.length) {
      session.selectSquare(square);
      return;
    }
    session.selectSquare(null);
  };

  const cells = [];
  for (let y = 0; y < 8; y += 1) {
    for (let x = 0; x < 8; x += 1) {
      const file = whiteSide ? FILES[x] : FILES[7 - x];
      const rank = whiteSide ? 8 - y : y + 1;
      const square = `${file}${rank}`;
      const highlight = highlightBySquare.get(square);
      const isTarget = legalTargets.has(square);
      const classes = [
        "cell",
        (x + y) % 2 === 0 ? "cell-light" : "cell-dark",
        lastMoveSquares.has(square) ? "cell-last" : "",
        square === selected ? "cell-selected" : "",
        isTarget ? (occupied.has(square) ? "cell-capture" : "cell-target") : "",
        highlight ? `cell-hl-${highlight}` : "",
        square === checkSquare ? "cell-check" : "",
      ]
        .filter(Boolean)
        .join(" ");
      cells.push(
        <button
          key={square}
          type="button"
          className={classes}
          style={{ animationDelay: `${(x + y) * 26}ms` }}
          aria-label={`Square ${square}${occupied.has(square) ? ", occupied" : ""}`}
          onClick={() => handleSquareClick(square)}
        />,
      );
    }
  }

  const fileLabels = whiteSide ? [...FILES] : [...FILES].reverse();
  const rankLabels = whiteSide ? [8, 7, 6, 5, 4, 3, 2, 1] : [1, 2, 3, 4, 5, 6, 7, 8];

  return (
    <div className="board-shell" data-voice={session.conversationState}>
      <div className="board-coords board-coords-ranks" aria-hidden="true">
        {rankLabels.map((rank) => (
          <span key={rank}>{rank}</span>
        ))}
      </div>
      <div className="board-coords board-coords-files" aria-hidden="true">
        {fileLabels.map((file) => (
          <span key={file}>{file}</span>
        ))}
      </div>
      <div className="board-field">
        <div className="board-grid">{cells}</div>
        <div className="board-pieces" aria-hidden="true">
          {pieces.map((piece) => (
            <span
              key={piece.id}
              className={`piece ${piece.code === piece.code.toUpperCase() ? "piece-white" : "piece-black"}`}
              style={{
                transform: `translate(${squareX(piece.square) * 100}%, ${squareY(piece.square) * 100}%)`,
              }}
            >
              {GLYPH[piece.code.toLowerCase()]}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
