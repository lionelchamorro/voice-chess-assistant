# Speech-synced actions: analysis and architecture

**Problem**: an agent speaks and simultaneously controls something (the chess
board) in function of what it is saying, as close to real time as possible.

**Key reframe**: this is not a tool-calling problem — it is a *timeline*
problem, and it is the same problem as avatar lip sync and gesture control.
The industry that solved it (talking avatars, karaoke captions, subtitles)
never asks the model to "call a tool at the right moment"; it anchors events
to positions in the speech text and fires them when the *audio playout clock*
reaches that position.

---

## The landscape (July 2026)

### What the industry does: SSML marks / bookmarks

- Azure TTS avatars trigger gestures with `<bookmark mark='gesture.*'/>`
  embedded in the SSML: the gesture starts exactly at the insertion point in
  the audio timeline.
- Google Cloud TTS emits *timepoint events* for `<mark>` tags: you get back
  "your marker X happens at 3.42s of this audio".
- LLM-driven pedagogical agents (research, 2026) have the LLM emit inline
  gesture/filler tags in its text output; a parser maps them to animations
  triggered in sync with speech.

This is the mature, proven pattern: **markers inline in the narration,
resolved to audio-timeline positions by the TTS, fired by a playout clock.**

### What speech-to-speech models offer (gpt-realtime, Gemini Live)

gpt-realtime (OpenAI) now supports *asynchronous function calling*: a
long-running tool no longer freezes the conversation; the model keeps talking
while the tool runs. That solves "don't block speech" — but it does **not**
give word-anchored timing. Tools still fire when *generated*, not when the
related words are *spoken*. You would still need the timeline overlay on top.
Verdict: watch, don't adopt for this; the cascaded pipeline keeps more
control.

### The research frontier: DuplexSLA (arXiv 2605.20755)

A full-duplex spoken language model with a **three-channel joint decoder**:
continuous user-audio channel, discrete assistant-audio channel, and a
rate-limited *action channel* — all decoded jointly on a 160ms-chunk
timeline. Speaking, listening, planning and acting are natively synchronized
in one backbone; no turn boundaries, no external VAD. This is exactly our
problem solved at the model level. It is research, not a product — but it
confirms the direction: **actions belong on the speech timeline, not in the
request/response loop.**

---

## Tiers for this codebase

### Tier 0 — what we have today (turn-level sync)

`SpeechPacer` + the `say` tool argument: board mutations wait until the
turn's audio starts, then apply after a lead. Precision ≈ ±1 second.
Two structural weaknesses:

1. Each move costs a *completion round-trip* (tool result → next completion
   → next sentence), so multi-move lessons have dead pauses between moves.
2. Sync is per-sentence, not per-word: "the knight jumps to f3 attacking the
   pawn" moves the piece somewhere in that window, not on "jumps".

### Tier 1 — the recommendation: Narrated Action Stream

The LLM produces **one continuous narration with inline action markers**
(our own micro-DSL, same idea as SSML bookmarks):

```
Now watch the center. ⟦e2e4⟧ White grabs space immediately, and after
⟦e7e5⟧ Black stakes his claim too. The real idea appears with ⟦g1f3⟧ —
the knight develops and hits e5 at the same time.
```

Runtime flow, mapped onto machinery **already present** in pipecat 0.0.108:

1. **`NarratedActionParser`** (new FrameProcessor between `llm` and `tts`):
   incrementally parses the `LLMTextFrame` stream, strips markers before the
   TTS ever sees them, forwards clean text, and registers each action with
   its anchor = character/word offset within the utterance.
2. **Word timestamps** — already on: `CartesiaTTSService` /
   `ElevenLabsTTSService` request word-level timestamps by default
   (`add_timestamps=True`) and assign a `pts` (presentation timestamp) to
   every `TTSTextFrame`.
3. **The transport clock** — `BaseOutputTransport` holds any frame with
   `pts` in a priority queue and releases it exactly when the pipeline clock
   reaches that instant. This is how word-by-word captions already work.
4. **`ActionScheduler`** (new FrameProcessor after `transport.output()`):
   watches the word-aligned `TTSTextFrame`s flow past in playout time,
   tracks the cumulative text offset per TTS context, and fires each
   registered action through `SessionManager` the moment its anchor word is
   spoken. On `InterruptionFrame`: discard all unfired actions — the board
   can never run ahead of what was actually said.

Properties:

- **Precision ≈ ±1 word (~150–300ms)** — the piece moves on the word.
- **No inter-move pauses**: one completion narrates a whole line; the pauses
  that tool round-trips cause today disappear.
- **Interruption-safe by construction**: unspoken ⇒ unplayed.
- **Coexists with tools**: keep `make_move`/`analyze_position` etc. for
  *reactive* work (answering a question, consulting the engine); markers are
  for *choreographed* teaching sequences. The system prompt routes: "to
  demonstrate lines, narrate with markers; to act on request, use tools."
- Marker syntax should be non-XML and rare (`⟦...⟧`) so a leak never gets
  pronounced; the parser also strips defensively on flush.
- Validation: markers resolve against the live board server-side exactly like
  tool moves do today (illegal marker ⇒ dropped + logged + optionally a
  corrective context message).

Estimated effort on this stack: ~1–2 days (two processors, prompt, tests).

### Tier 1.5 — client-edge scheduling (the last 100ms)

Server-side pts firing is aligned to the *server's* playout pacing; network
jitter adds ~50–150ms noise at the browser. The refinement used by
karaoke/subtitle systems: send board events *early* tagged with
`audioTimeMs` relative to the utterance, and let the client fire them
against its own audio playback clock (AudioContext time). Only worth doing
if Tier 1 feels off; for chess (unlike lip sync) ±200ms is imperceptible.

### Tier 2 — the frontier bet

When full-duplex models with native action channels (DuplexSLA-style) or
word-anchored tool timing in gpt-realtime become products, the marker DSL
becomes the model's native action stream and the parser disappears. The
Tier-1 investment survives: `ActionScheduler`, validation, and the board
protocol are exactly the pieces those models will need downstream.

---

## Sources

- [Azure TTS avatar gestures via SSML bookmarks](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/text-to-speech-avatar/avatar-gestures-with-ssml)
- [Google Cloud TTS SSML `<mark>` timepoints](https://docs.cloud.google.com/text-to-speech/docs/ssml)
- [DuplexSLA: full-duplex spoken LM with synchronized speech, language and action](https://arxiv.org/abs/2605.20755)
- [Dynamic multimodal expression generation for LLM-driven pedagogical agents](https://arxiv.org/pdf/2603.09536)
- [Introducing gpt-realtime — async function calling](https://openai.com/index/introducing-gpt-realtime/)
- [OpenAI Realtime API: The Missing Manual](https://www.latent.space/p/realtime-api)
- [Pipecat TTS word timestamps](https://docs.pipecat.ai/pipecat/learn/text-to-speech)
- [Inworld: timestamp alignment for word/phoneme/viseme sync](https://inworld.ai/blog/tts-custom-pronunciation-timestamps-websockets)
- Local verification: pipecat 0.0.108 — `CartesiaTTSService(add_timestamps=True)`,
  `TTSService._add_word_timestamps` (pts assignment), and
  `BaseOutputTransport._clock_task_handler` (pts-scheduled frame release).
