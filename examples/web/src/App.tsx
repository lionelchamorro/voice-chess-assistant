import { useState } from "react";

import {
  VoiceChessBoard,
  VoiceChessProvider,
  VoiceChessStatus,
  useVoiceChessSession,
} from "@voice-chess/react";

const DEFAULT_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1";
const DEFAULT_PGN = `1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6`;

export function App() {
  const [sessionId] = useState(() => "demo-session");
  const [boardSocketBaseUrl, setBoardSocketBaseUrl] = useState(defaultBoardSocketBaseUrl());

  return (
    <main className="app-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Voice Chess Example</p>
          <h1>Controlled board demo wired against the backend protocol.</h1>
          <p className="lede">
            This example focuses on the canonical board session and is structured
            to integrate the Pipecat voice transport in the same workspace layout.
          </p>
        </div>
        <label className="field">
          <span>Board socket base URL</span>
          <input
            value={boardSocketBaseUrl}
            onChange={(event) => setBoardSocketBaseUrl(event.target.value)}
          />
        </label>
      </section>

      <VoiceChessProvider
        key={`${boardSocketBaseUrl}::${sessionId}`}
        boardSocketUrl={boardSocketBaseUrl}
        sessionId={sessionId}
        autoConnect={false}
      >
        <ExampleWorkspace />
      </VoiceChessProvider>
    </main>
  );
}

function ExampleWorkspace() {
  const {
    boardState,
    connectionStatus,
    connect,
    disconnect,
    loadFen,
    loadPgn,
    navigate,
    resetBoard,
  } = useVoiceChessSession();
  const [fenInput, setFenInput] = useState(DEFAULT_FEN);
  const [pgnInput, setPgnInput] = useState(DEFAULT_PGN);

  return (
    <section className="workspace">
      <section className="board-column card">
        <div className="board-toolbar">
          <div>
            <strong>Session board</strong>
            <p className="muted">
              Status: {connectionStatus} {boardState ? `· Turn ${boardState.turn}` : ""}
            </p>
          </div>
          <div className="button-row">
            <button onClick={() => void connect()}>Connect</button>
            <button onClick={disconnect}>Disconnect</button>
            <button onClick={resetBoard}>Reset</button>
          </div>
        </div>
        <VoiceChessBoard className="board-surface" />
      </section>

      <section className="side-column">
        <div className="card">
          <VoiceChessStatus />
        </div>

        <div className="card">
          <div className="card-header">
            <strong>Load FEN</strong>
            <button onClick={() => loadFen(fenInput)}>Apply</button>
          </div>
          <textarea value={fenInput} onChange={(event) => setFenInput(event.target.value)} />
        </div>

        <div className="card">
          <div className="card-header">
            <strong>Load PGN</strong>
            <div className="button-row">
              <button onClick={() => loadPgn(pgnInput)}>Load live</button>
              <button onClick={() => loadPgn(pgnInput, 0)}>Load from ply 0</button>
            </div>
          </div>
          <textarea value={pgnInput} onChange={(event) => setPgnInput(event.target.value)} />
        </div>

        <div className="card">
          <div className="card-header">
            <strong>Navigate</strong>
            <div className="button-row">
              <button onClick={() => navigate(null)}>Live</button>
              <button onClick={() => navigate(Math.max((boardState?.moveHistory.length ?? 1) - 1, 0))}>
                Previous
              </button>
              <button onClick={() => navigate(boardState?.moveHistory.length ?? 0)}>Latest ply</button>
            </div>
          </div>
          <ol className="move-list">
            {(boardState?.moveHistory ?? []).map((move) => (
              <li key={move.ply}>
                <button className="move-button" onClick={() => navigate(move.ply)}>
                  {move.ply}. {move.san}
                </button>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </section>
  );
}

function defaultBoardSocketBaseUrl() {
  if (typeof window === "undefined") {
    return "ws://localhost:7860/ws/sessions";
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.hostname}:7860/ws/sessions`;
}
