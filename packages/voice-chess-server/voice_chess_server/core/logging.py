"""Logging configuration."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import IO, Any

import structlog


class _TeeWriter:
    """Write log lines to several streams at once (stdout + file)."""

    def __init__(self, *streams: IO[str]) -> None:
        self._streams = streams

    def write(self, message: str) -> None:
        for stream in self._streams:
            stream.write(message)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def configure_logging(level: str, log_file: str | None = None) -> None:
    """Configure stdlib and structlog; optionally tee everything to a file.

    When `log_file` is set, both our structlog events and pipecat's loguru
    output (TTS/STT/transport internals) are appended there, so a session can
    be diagnosed after the fact without scraping the terminal.
    """

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        stream=sys.stdout,
    )

    factory_kwargs: dict[str, Any] = {}
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_stream = path.open("a", encoding="utf-8")
        factory_kwargs["file"] = _TeeWriter(sys.stdout, file_stream)
        try:
            from loguru import logger as loguru_logger

            loguru_logger.add(str(path), level=level.upper(), enqueue=True)
        except ImportError:
            pass

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(**factory_kwargs),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
    )
