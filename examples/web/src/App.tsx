import { useMemo, useState } from "react";

import {
  VoiceChessBoard,
  VoiceChessProvider,
  VoiceChessStatus,
  VoiceChessVoiceControls,
  useVoiceChessSession,
} from "@voice-chess/react";

const DEFAULT_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1";
const DEFAULT_PGN = `1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6`;
const DEMO_PROMPTS = [
  "Play e2 to e4",
  "Highlight e4",
  "Clear highlights",
  "Undo the last move",
];

export function App() {
  const [sessionId] = useState(() => "demo-session");
  const [boardSocketBaseUrl, setBoardSocketBaseUrl] = useState(defaultBoardSocketBaseUrl());
  const [signalingApiUrl, setSignalingApiUrl] = useState(defaultSignalingApiUrl());

  return (
    <main className="app-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Voice Chess Assistant</p>
          <h1>Talk to the assistant and let the board react to each turn.</h1>
          <p className="lede">
            Join voice and the assistant immediately starts walking through an opening on the board.
            You can interrupt, ask questions, or steer the analysis at any point.
          </p>
        </div>
        <div className="hero-fields">
          <label className="field">
            <span>Board socket base URL</span>
            <input
              value={boardSocketBaseUrl}
              onChange={(event) => setBoardSocketBaseUrl(event.target.value)}
            />
          </label>
          <label className="field">
            <span>Signaling API URL</span>
            <input
              value={signalingApiUrl}
              onChange={(event) => setSignalingApiUrl(event.target.value)}
            />
          </label>
        </div>
      </section>

      <VoiceChessProvider
        key={`${boardSocketBaseUrl}::${signalingApiUrl}::${sessionId}`}
        boardSocketUrl={boardSocketBaseUrl}
        signalingApiUrl={signalingApiUrl}
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
    conversationState,
    toolCalls,
    connect,
    disconnect,
    loadFen,
    loadPgn,
    navigate,
    requestDemoPrompt,
    resetBoard,
  } = useVoiceChessSession();
  const [fenInput, setFenInput] = useState(DEFAULT_FEN);
  const [pgnInput, setPgnInput] = useState(DEFAULT_PGN);
  const [promptInput, setPromptInput] = useState("Play e2 to e4");

  const toolTimeline = useMemo(() => toolCalls.slice(-8).reverse(), [toolCalls]);

  function sendPrompt(prompt: string) {
    requestDemoPrompt(prompt);
    setPromptInput(prompt);
  }

  return (
    <section className="workspace">
      <section className="conversation-column">
        <div className="card conversation-card">
          <div className="conversation-topbar">
            <div>
              <strong>Conversation</strong>
              <p className="muted">
                Board socket: {connectionStatus} · Assistant state: {conversationState}
              </p>
            </div>
            <div className="button-row">
              <button onClick={() => void connect()}>Connect session</button>
              <button onClick={disconnect}>Disconnect</button>
            </div>
          </div>

          <div className="prompt-composer">
            <textarea
              aria-label="Assistant prompt"
              value={promptInput}
              onChange={(event) => setPromptInput(event.target.value)}
              placeholder="Describe the move or board action you want the assistant to perform"
            />
            <div className="button-row wrap-row">
              <button onClick={() => sendPrompt(promptInput)}>Send prompt</button>
              {DEMO_PROMPTS.map((prompt) => (
                <button key={prompt} className="secondary-button" onClick={() => sendPrompt(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
          </div>

          <section className="tool-panel">
            <div className="section-heading">
              <strong>Tool activity</strong>
              <span>{toolTimeline.length} events</span>
            </div>
            <div className="tool-list" data-testid="tool-call-list">
              {toolTimeline.length ? (
                toolTimeline.map((toolCall) => (
                  <article key={toolCall.id} className="tool-entry" data-testid="tool-call-item">
                    <header>
                      <strong>{toolCall.toolName}</strong>
                      <span>{toolCall.status}</span>
                    </header>
                    <p>{toolCall.summary}</p>
                  </article>
                ))
              ) : (
                <p className="empty-state">Tool calls will appear here when the assistant acts.</p>
              )}
            </div>
          </section>
        </div>

        <div className="card utility-grid">
          <div>
            <VoiceChessVoiceControls />
          </div>
          <div>
            <VoiceChessStatus />
          </div>
        </div>

        <div className="card utility-stack">
          <div className="card-header">
            <strong>Position control</strong>
            <div className="button-row">
              <button onClick={resetBoard}>Reset</button>
              <button onClick={() => navigate(null)}>Live board</button>
            </div>
          </div>

          <label className="field">
            <span>Load FEN</span>
            <textarea value={fenInput} onChange={(event) => setFenInput(event.target.value)} />
            <button onClick={() => loadFen(fenInput)}>Apply FEN</button>
          </label>

          <label className="field">
            <span>Load PGN</span>
            <textarea value={pgnInput} onChange={(event) => setPgnInput(event.target.value)} />
            <div className="button-row wrap-row">
              <button onClick={() => loadPgn(pgnInput)}>Load live</button>
              <button onClick={() => loadPgn(pgnInput, 0)}>Load from ply 0</button>
              <button onClick={() => navigate(Math.max((boardState?.moveHistory.length ?? 1) - 1, 0))}>
                Previous ply
              </button>
              <button onClick={() => navigate(boardState?.moveHistory.length ?? 0)}>Latest ply</button>
            </div>
          </label>
        </div>
      </section>

      <section className="board-column card board-card">
        <div className="board-toolbar">
          <div>
            <strong>Canonical board</strong>
            <p className="muted">
              {boardState
                ? `Turn ${boardState.turn} · ${boardState.moveHistory.length} moves recorded`
                : "Waiting for the session board."}
            </p>
          </div>
        </div>
        <VoiceChessBoard className="board-surface" />

        <section className="move-history-panel">
          <div className="section-heading">
            <strong>Move history</strong>
            <span>{boardState?.moveHistory.length ?? 0} plies</span>
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
        </section>
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

function defaultSignalingApiUrl() {
  if (typeof window === "undefined") {
    return "http://localhost:7860";
  }
  const protocol = window.location.protocol === "https:" ? "https:" : "http:";
  return `${protocol}//${window.location.hostname}:7860`;
}
