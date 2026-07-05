"""Narrated action stream: inline markers anchored to the speech timeline.

The LLM writes one continuous narration with inline markers — the same idea
as SSML ``<mark>`` bookmarks used for avatar gestures::

    White grabs the center [[move e2e4]] and Black answers [[move e7e5]].

`StreamMarkerParser` strips the markers from the streamed text before the TTS
ever sees them and anchors each action to its character offset in the clean
text. The TTS returns word-level timestamps, the output transport releases
each word frame at its playout instant, and `ChoreographyState` fires each
action the moment its anchor word is spoken — so the board moves on the word.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass

MARKER_OPEN = "[["
MARKER_CLOSE = "]]"
# A marker body longer than this is treated as literal text (a runaway "[[").
# Models sometimes invent verbose marker bodies (tool names plus an embedded
# say:"..." argument), so the limit is generous: bracket content must never
# reach the TTS.
MAX_MARKER_BODY = 200

_UCI_PATTERN = re.compile(r"^([a-h][1-8])([a-h][1-8])([qrbn])?$")
_MARKER_PATTERN = re.compile(r"\[\[[^\[\]]{0,200}\]\]")
# Embedded narration arguments inside a marker body (say:"...", say='...',
# say=...) are noise: the narration lives outside the marker.
_EMBEDDED_SAY_PATTERN = re.compile(r"say\s*[:=]\s*(\"[^\"]*\"|'[^']*'|\S+)", re.IGNORECASE)

# Models conflate tool names with marker verbs; accept both spellings.
VERB_ALIASES: dict[str, str] = {
    "make_move": "move",
    "play": "move",
    "show_next_move": "next",
    "next_move": "next",
    "show_previous_move": "prev",
    "previous_move": "prev",
    "back": "prev",
    "go_to_move": "goto",
    "go_to": "goto",
    "reset_board": "reset",
    "play_variation_move": "var",
    "variation": "var",
    "end_variation": "endvar",
    "set_highlight": "highlight",
    "set_highlights": "highlight",
    "clear_highlights": "clear",
}


def strip_markers(text: str) -> str:
    """Remove [[...]] markers from text that is about to be spoken.

    Weak models sometimes leak markers into places meant for plain speech
    (e.g. the `say` tool argument); the TTS must never read them aloud.
    """

    return _MARKER_PATTERN.sub("", text)


def normalize_san(san: str) -> str:
    """Normalize a SAN string for comparison (checks, mate, annotations)."""

    return san.strip().rstrip("+#!?").replace("0-0-0", "O-O-O").replace("0-0", "O-O")


PROMOTION_NAME_BY_LETTER = {
    "q": "queen",
    "r": "rook",
    "b": "bishop",
    "n": "knight",
}


@dataclass(slots=True)
class ActionCue:
    """An action anchored to a clean-text character offset.

    `sequence` identifies the LLM completion the cue belongs to: generation
    runs ahead of playout, so cues for a completion that is still being
    generated must not fire against the audio of the previous one.
    """

    anchor: int
    spec: str
    sequence: int = 0


@dataclass(slots=True)
class NarratedAction:
    """A parsed marker body."""

    verb: str
    args: list[str]


def parse_action_spec(spec: str) -> NarratedAction | None:
    """Parse a marker body like ``move e2e4`` into a NarratedAction.

    Tolerates model improvisations: tool names instead of marker verbs
    (``show_next_move`` → ``next``) and embedded ``say:"..."`` arguments,
    which are dropped — narration belongs outside the marker.
    """

    cleaned = _EMBEDDED_SAY_PATTERN.sub("", spec)
    parts = cleaned.strip().split()
    if not parts:
        return None
    verb = parts[0].lower()
    verb = VERB_ALIASES.get(verb, verb)
    return NarratedAction(verb=verb, args=parts[1:])


def move_arguments(argument: str) -> dict[str, str | None]:
    """Interpret a move argument as UCI coordinates or SAN."""

    match = _UCI_PATTERN.match(argument.strip())
    if match:
        promotion_letter = match.group(3)
        return {
            "from_square": match.group(1),
            "to_square": match.group(2),
            "promotion": PROMOTION_NAME_BY_LETTER.get(promotion_letter or ""),
            "san": None,
        }
    return {"from_square": None, "to_square": None, "promotion": None, "san": argument.strip()}


class StreamMarkerParser:
    """Incrementally strip ``[[...]]`` markers from streamed LLM text.

    Safe against markers split across stream chunks: a possible marker prefix
    is held back until it either completes, exceeds MAX_MARKER_BODY, or the
    stream is flushed.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._clean_offset = 0

    def reset(self) -> None:
        self._buffer = ""
        self._clean_offset = 0

    def feed(self, chunk: str) -> tuple[str, list[ActionCue]]:
        """Consume a stream chunk; return (clean text, completed action cues)."""

        self._buffer += chunk
        clean_parts: list[str] = []
        cues: list[ActionCue] = []

        while self._buffer:
            open_index = self._buffer.find(MARKER_OPEN)
            if open_index == -1:
                # No marker start: emit everything except a trailing "[" that
                # could become "[[" with the next chunk.
                holdback = 1 if self._buffer.endswith("[") else 0
                emit = self._buffer[: len(self._buffer) - holdback]
                if emit:
                    clean_parts.append(emit)
                    self._clean_offset += len(emit)
                self._buffer = self._buffer[len(self._buffer) - holdback :]
                break

            # Emit the text before the marker.
            if open_index:
                emit = self._buffer[:open_index]
                clean_parts.append(emit)
                self._clean_offset += len(emit)
                self._buffer = self._buffer[open_index:]

            close_index = self._buffer.find(MARKER_CLOSE, len(MARKER_OPEN))
            if close_index == -1:
                if len(self._buffer) - len(MARKER_OPEN) > MAX_MARKER_BODY:
                    # Runaway "[[" with no close: treat as literal text.
                    clean_parts.append(self._buffer)
                    self._clean_offset += len(self._buffer)
                    self._buffer = ""
                # Otherwise hold the partial marker until the next chunk.
                break

            body = self._buffer[len(MARKER_OPEN) : close_index]
            if body.strip():
                cues.append(ActionCue(anchor=self._clean_offset, spec=body.strip()))
            self._buffer = self._buffer[close_index + len(MARKER_CLOSE) :]

        return "".join(clean_parts), cues

    def flush(self) -> str:
        """End of stream: return remaining literal text, dropping any
        unterminated marker so the TTS never reads a half-marker aloud."""

        remainder = self._buffer
        self._buffer = ""
        open_index = remainder.find(MARKER_OPEN)
        if open_index != -1:
            remainder = remainder[:open_index]
        self._clean_offset += len(remainder)
        return remainder


class ChoreographyState:
    """Fire registered action cues as their anchor words are spoken.

    The parser registers cues at generation speed; the spoken-character
    counter advances at playout speed (one word-timestamped TTSTextFrame at a
    time). A cue fires once the playout counter crosses its anchor — but only
    while the completion it belongs to is the one currently playing:
    generation runs ahead of audio, so `on_generation_start` (parser side)
    and `on_playout_start` (scheduler side, ordered with the audio stream)
    advance two independent sequence counters.
    """

    def __init__(self) -> None:
        self._pending: deque[ActionCue] = deque()
        self._spoken_chars = 0
        self._generation_sequence = 0
        self._playout_sequence = 0

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def generation_sequence(self) -> int:
        return self._generation_sequence

    def on_generation_start(self) -> None:
        """Parser side: a new LLM completion started generating."""

        self._generation_sequence += 1

    def on_playout_start(self) -> None:
        """Scheduler side: that completion's stream reached the playout edge."""

        self._playout_sequence += 1
        self._spoken_chars = 0

    def register(self, cue: ActionCue) -> None:
        self._pending.append(cue)

    def on_word_spoken(self, word: str) -> list[ActionCue]:
        """Advance the playout counter; return cues whose anchor was crossed."""

        self._spoken_chars += len(word) + 1
        ready: list[ActionCue] = []
        while (
            self._pending
            and self._pending[0].sequence == self._playout_sequence
            and self._pending[0].anchor <= self._spoken_chars
        ):
            ready.append(self._pending.popleft())
        return ready

    def drain(self) -> list[ActionCue]:
        """Speech finished: fire what remains of the completion that played."""

        ready: list[ActionCue] = []
        while self._pending and self._pending[0].sequence <= self._playout_sequence:
            ready.append(self._pending.popleft())
        return ready

    def clear(self) -> None:
        """Interruption: unspoken narration must never reach the board."""

        self._pending.clear()
