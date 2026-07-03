import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import { VoiceChessProvider, useVoiceChessSession } from "@voice-chess/react";

import { LivingBoard } from "./components/LivingBoard";

const DEFAULT_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1";
const DEFAULT_PGN = "1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6";
const DEMO_PROMPTS = [
  "Play e2 to e4",
  "Highlight e4",
  "Clear highlights",
  "Undo the last move",
];

interface Endpoints {
  boardSocketUrl: string;
  signalingApiUrl: string;
}

export function App() {
  const [endpoints, setEndpoints] = useState<Endpoints>(() => ({
    boardSocketUrl: defaultBoardSocketBaseUrl(),
    signalingApiUrl: defaultSignalingApiUrl(),
  }));
  const sessionId = "demo-session";

  return (
    <VoiceChessProvider
      key={`${endpoints.boardSocketUrl}::${endpoints.signalingApiUrl}::${sessionId}`}
      boardSocketUrl={endpoints.boardSocketUrl}
      signalingApiUrl={endpoints.signalingApiUrl}
      sessionId={sessionId}
      autoConnect={false}
    >
      <Studio sessionId={sessionId} endpoints={endpoints} onEndpointsChange={setEndpoints} />
      <AudioSink />
    </VoiceChessProvider>
  );
}

function Studio({
  sessionId,
  endpoints,
  onEndpointsChange,
}: {
  sessionId: string;
  endpoints: Endpoints;
  onEndpointsChange: (endpoints: Endpoints) => void;
}) {
  const {
    boardState,
    connectionStatus,
    conversationState,
    conversationMessages,
    toolCalls,
    errorMessage,
    connect,
    disconnect,
    navigate,
    loadFen,
    loadPgn,
    requestDemoPrompt,
    resetBoard,
  } = useVoiceChessSession();

  const connected = connectionStatus === "connected";
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="studio">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ♞
          </span>
          <span className="brand-name">Voice Chess</span>
          <span className="brand-tag">coach</span>
        </div>
        <div className="topbar-actions">
          <span className="session-chip">
            session <strong>{sessionId}</strong>
          </span>
          <span className="conn-chip" data-conn={connectionStatus} data-testid="connection-status">
            {connectionStatus}
          </span>
          {connected ? (
            <button type="button" className="btn btn-ghost" onClick={disconnect}>
              Disconnect
            </button>
          ) : (
            <button type="button" className="btn btn-primary" onClick={() => void connect()}>
              Connect session
            </button>
          )}
          <button
            type="button"
            className="btn btn-icon"
            aria-label="Endpoint settings"
            aria-expanded={settingsOpen}
            onClick={() => setSettingsOpen((open) => !open)}
          >
            ⚙
          </button>
        </div>
        {settingsOpen ? (
          <SettingsPanel
            endpoints={endpoints}
            onApply={(next) => {
              setSettingsOpen(false);
              onEndpointsChange(next);
            }}
          />
        ) : null}
      </header>

      <main className="workspace">
        <aside className="rail">
          <section className="intro">
            <p className="eyebrow">Your AI chess teacher</p>
            <h1>Voice Chess Coach</h1>
            <p className="lede">
              A coach that talks — and moves the pieces on the board while it explains.
            </p>
          </section>

          <VoiceDock />
          <Transcript messages={conversationMessages} conversationState={conversationState} />
          <Composer
            disabled={!connected}
            onSend={(prompt) => {
              requestDemoPrompt(prompt);
            }}
          />
        </aside>

        <section className="stage">
          <div className="stage-toolbar">
            <div className="stage-facts">
              <span className="fact-chip" data-testid="board-turn">
                {boardState ? `${boardState.turn} to move` : "no position"}
              </span>
              <span className="fact-chip fact-quiet" data-testid="board-view">
                {boardState?.viewMode === "review"
                  ? `reviewing ply ${boardState.reviewPly}`
                  : "live"}
              </span>
              {boardState?.variation?.length ? (
                <span className="fact-chip fact-variation" data-testid="board-variation">
                  sideline: {boardState.variation.join(" ")}
                </span>
              ) : null}
              {boardState?.isCheck ? <span className="fact-chip fact-check">check</span> : null}
              {boardState?.isCheckmate ? (
                <span className="fact-chip fact-check">checkmate</span>
              ) : null}
            </div>
            <div className="stage-tools">
              {boardState?.viewMode === "review" ? (
                <button type="button" className="btn btn-ghost" onClick={() => navigate(null)}>
                  Return to live
                </button>
              ) : null}
              <button
                type="button"
                className="btn btn-ghost"
                disabled={!connected}
                onClick={resetBoard}
              >
                Reset
              </button>
            </div>
          </div>

          <div className="stage-grid">
            <LivingBoard />
            <ScoreSheet />
          </div>

          {errorMessage ? (
            <p className="board-error" data-testid="board-error" role="status">
              {errorMessage}
            </p>
          ) : null}

          <EngineLog toolCalls={toolCalls} />

          <details className="position-tools">
            <summary>Position tools</summary>
            <PositionTools
              disabled={!connected}
              onLoadFen={loadFen}
              onLoadPgn={loadPgn}
            />
          </details>
        </section>
      </main>
    </div>
  );
}

function VoiceDock() {
  const {
    conversationState,
    voiceConnectionStatus,
    voiceTransportAvailable,
    voiceTransportReason,
    microphonePermissionStatus,
    voiceErrorMessage,
    connectVoice,
    disconnectVoice,
  } = useVoiceChessSession();

  const voiceActive =
    voiceConnectionStatus === "connected" ||
    voiceConnectionStatus === "connecting" ||
    voiceConnectionStatus === "requesting_media";

  return (
    <section className="voice-dock" data-testid="voice-controls">
      <div className="voice-row">
        <span className="sigil" data-voice={conversationState} aria-hidden="true">
          <span className="sigil-core" />
        </span>
        <div className="voice-copy">
          <span className="voice-state" data-testid="conversation-state">
            {conversationState}
          </span>
          <span className="voice-sub" data-testid="voice-connection-status">
            voice {voiceConnectionStatus} · mic {microphonePermissionStatus}
          </span>
        </div>
        {voiceActive ? (
          <button type="button" className="btn btn-ghost" onClick={disconnectVoice}>
            Leave voice
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-primary"
            disabled={!voiceTransportAvailable}
            onClick={() => void connectVoice()}
          >
            Join voice
          </button>
        )}
      </div>
      {!voiceTransportAvailable ? (
        <p className="voice-note" data-testid="voice-unavailable">
          Voice is offline: {voiceTransportReason ?? "the server voice runtime is not ready."}
        </p>
      ) : null}
      {voiceErrorMessage ? (
        <p className="voice-note voice-note-error" data-testid="voice-error-inline">
          {voiceErrorMessage}
        </p>
      ) : null}
    </section>
  );
}

function Transcript({
  messages,
  conversationState,
}: {
  messages: { id: string; role: string; content: string }[];
  conversationState: string;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = scrollRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [messages.length, conversationState]);

  return (
    <section className="transcript">
      <header className="panel-heading">
        <span>Conversation</span>
        <span className="panel-count">{messages.length}</span>
      </header>
      <div className="transcript-scroll" ref={scrollRef} data-testid="conversation-messages">
        {messages.length === 0 ? (
          <p className="empty-note">
            Connect the session and say hello — ask for moves, plans, or a position review.
          </p>
        ) : (
          messages.map((message) => (
            <article
              key={message.id}
              className="say"
              data-role={message.role}
              data-testid="conversation-message"
            >
              <span className="say-role">{message.role === "assistant" ? "coach" : message.role}</span>
              <p>{message.content}</p>
            </article>
          ))
        )}
        {conversationState === "thinking" ? (
          <article className="say say-pending" data-role="assistant" aria-hidden="true">
            <span className="say-role">coach</span>
            <p className="thinking-dots">
              <span />
              <span />
              <span />
            </p>
          </article>
        ) : null}
      </div>
    </section>
  );
}

function Composer({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (prompt: string) => void;
}) {
  const [prompt, setPrompt] = useState("Play e2 to e4");

  const send = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || disabled) {
      return;
    }
    onSend(trimmed);
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    send(prompt);
  };

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <textarea
        aria-label="Assistant prompt"
        value={prompt}
        rows={2}
        onChange={(event) => setPrompt(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            send(prompt);
          }
        }}
        placeholder="Ask for a move, a plan, a position…"
      />
      <div className="composer-row">
        <button type="submit" className="btn btn-primary" disabled={disabled}>
          Send prompt
        </button>
        <div className="chip-row" role="group" aria-label="Example prompts">
          {DEMO_PROMPTS.map((demoPrompt) => (
            <button
              key={demoPrompt}
              type="button"
              className="chip-btn"
              disabled={disabled}
              onClick={() => {
                setPrompt(demoPrompt);
                send(demoPrompt);
              }}
            >
              {demoPrompt}
            </button>
          ))}
        </div>
      </div>
    </form>
  );
}

function ScoreSheet() {
  const { boardState, navigate } = useVoiceChessSession();
  const history = boardState?.moveHistory ?? [];
  const viewPly =
    boardState?.viewMode === "review" ? (boardState.reviewPly ?? 0) : history.length;

  const rows = useMemo(() => {
    const paired: {
      number: number;
      white: (typeof history)[number] | undefined;
      black: (typeof history)[number] | undefined;
    }[] = [];
    for (let index = 0; index < history.length; index += 2) {
      paired.push({
        number: index / 2 + 1,
        white: history[index],
        black: history[index + 1],
      });
    }
    return paired;
  }, [history]);

  return (
    <aside className="scoresheet">
      <header className="panel-heading">
        <span>Score sheet</span>
        <div className="sheet-nav">
          <button
            type="button"
            className="btn btn-icon"
            aria-label="Previous move"
            disabled={!boardState || viewPly === 0}
            onClick={() => navigate(Math.max(viewPly - 1, 0))}
          >
            ‹
          </button>
          <button
            type="button"
            className="btn btn-icon"
            aria-label="Next move"
            disabled={!boardState || viewPly >= history.length}
            onClick={() => {
              const next = viewPly + 1;
              navigate(next >= history.length ? null : next);
            }}
          >
            ›
          </button>
        </div>
      </header>
      <div className="sheet-scroll">
        {rows.length === 0 ? (
          <p className="empty-note">No moves yet.</p>
        ) : (
          <table>
            <tbody>
              {rows.map((row) => (
                <tr key={row.number}>
                  <td className="sheet-number">{row.number}.</td>
                  {[row.white, row.black].map((move, columnIndex) =>
                    move ? (
                      <td key={columnIndex}>
                        <button
                          type="button"
                          className={`sheet-move${move.ply === viewPly ? " sheet-move-current" : ""}`}
                          onClick={() => navigate(move.ply)}
                        >
                          {move.san}
                        </button>
                      </td>
                    ) : (
                      <td key={columnIndex} />
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </aside>
  );
}

function EngineLog({
  toolCalls,
}: {
  toolCalls: { id: string; toolName: string; status: string; summary: string }[];
}) {
  const entries = useMemo(() => toolCalls.slice(-24).reverse(), [toolCalls]);

  return (
    <section className="engine-log">
      <header className="panel-heading">
        <span>Engine room</span>
        <span className="panel-count">{entries.length}</span>
      </header>
      <div className="log-scroll" data-testid="tool-call-list">
        {entries.length === 0 ? (
          <p className="empty-note">Tool calls appear here as the coach acts on the board.</p>
        ) : (
          entries.map((toolCall) => (
            <p key={toolCall.id} className="log-line" data-testid="tool-call-item">
              <span className="log-dot" data-status={toolCall.status} aria-hidden="true" />
              <span className="log-tool">{toolCall.toolName}</span>
              <span className="log-summary">{toolCall.summary}</span>
            </p>
          ))
        )}
      </div>
    </section>
  );
}

function PositionTools({
  disabled,
  onLoadFen,
  onLoadPgn,
}: {
  disabled: boolean;
  onLoadFen: (fen: string) => void;
  onLoadPgn: (pgn: string, startPly?: number | null) => void;
}) {
  const [fenInput, setFenInput] = useState(DEFAULT_FEN);
  const [pgnInput, setPgnInput] = useState(DEFAULT_PGN);

  return (
    <div className="position-grid">
      <label className="field">
        <span>FEN</span>
        <textarea value={fenInput} rows={2} onChange={(event) => setFenInput(event.target.value)} />
        <button
          type="button"
          className="btn btn-ghost"
          disabled={disabled}
          onClick={() => onLoadFen(fenInput)}
        >
          Load FEN
        </button>
      </label>
      <label className="field">
        <span>PGN</span>
        <textarea value={pgnInput} rows={2} onChange={(event) => setPgnInput(event.target.value)} />
        <div className="field-row">
          <button
            type="button"
            className="btn btn-ghost"
            disabled={disabled}
            onClick={() => onLoadPgn(pgnInput)}
          >
            Load PGN
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={disabled}
            onClick={() => onLoadPgn(pgnInput, 0)}
          >
            Review from start
          </button>
        </div>
      </label>
    </div>
  );
}

function SettingsPanel({
  endpoints,
  onApply,
}: {
  endpoints: Endpoints;
  onApply: (endpoints: Endpoints) => void;
}) {
  const [boardDraft, setBoardDraft] = useState(endpoints.boardSocketUrl);
  const [signalDraft, setSignalDraft] = useState(endpoints.signalingApiUrl);

  return (
    <div className="settings-panel">
      <label className="field">
        <span>Board socket base URL</span>
        <input value={boardDraft} onChange={(event) => setBoardDraft(event.target.value)} />
      </label>
      <label className="field">
        <span>Signaling API URL</span>
        <input value={signalDraft} onChange={(event) => setSignalDraft(event.target.value)} />
      </label>
      <button
        type="button"
        className="btn btn-primary"
        onClick={() => onApply({ boardSocketUrl: boardDraft, signalingApiUrl: signalDraft })}
      >
        Apply and reconnect
      </button>
    </div>
  );
}

function AudioSink() {
  const { remoteAudioStream } = useVoiceChessSession();
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const audioElement = audioRef.current;
    if (!audioElement) {
      return;
    }
    audioElement.srcObject = remoteAudioStream;
    if (remoteAudioStream) {
      void audioElement.play().catch(() => {
        // Autoplay can stay blocked until the user interacts with the page.
      });
    }
    return () => {
      audioElement.pause();
      audioElement.srcObject = null;
    };
  }, [remoteAudioStream]);

  return <audio ref={audioRef} autoPlay playsInline hidden />;
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
