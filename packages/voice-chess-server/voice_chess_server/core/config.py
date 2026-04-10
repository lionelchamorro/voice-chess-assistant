"""Application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_prefix="VOICE_CHESS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "voice-chess-server"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    host: str = "0.0.0.0"
    port: int = 7860

    transport: Literal["smallwebrtc"] = "smallwebrtc"

    llm_provider: Literal["openai"] = "openai"
    llm_model: str = "gpt-4o-mini"
    stt_provider: Literal["deepgram"] = "deepgram"
    tts_provider: Literal["elevenlabs", "cartesia"] = "elevenlabs"
    system_prompt: str = (
        "You are a chess analysis voice assistant. Speak clearly and briefly. "
        "Use the available tools whenever you need to inspect or manipulate the board. "
        "When making a move, explain why it matters. Prefer legal, concrete moves. "
        "When the session starts, briefly introduce yourself and offer to analyze "
        "the current position or a PGN the user provides."
    )

    openai_api_key: str | None = Field(default=None, repr=False)
    deepgram_api_key: str | None = Field(default=None, repr=False)
    elevenlabs_api_key: str | None = Field(default=None, repr=False)
    elevenlabs_voice_id: str | None = None
    cartesia_api_key: str | None = Field(default=None, repr=False)
    cartesia_voice_id: str | None = None
    cartesia_model: str = "sonic-3"

    stun_urls: tuple[str, ...] = ("stun:stun.l.google.com:19302",)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings."""

    return Settings()
