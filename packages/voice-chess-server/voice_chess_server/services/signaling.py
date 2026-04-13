"""WebRTC signaling service with lazy Pipecat imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from voice_chess_server.schemas.signaling import OfferRequest, OfferResponse

log = structlog.get_logger()


class SignalingRuntimeError(RuntimeError):
    """Raised when signaling runtime dependencies are not available."""


@dataclass(frozen=True, slots=True)
class IceServerConfig:
    """Serializable ICE server config."""

    urls: str
    username: str | None = None
    credential: str | None = None


class SmallWebRTCSignalingService:
    """Manage SmallWebRTC peer connections."""

    def __init__(self, ice_servers: tuple[IceServerConfig, ...]) -> None:
        self._ice_servers = ice_servers
        self._peer_connections: dict[str, Any] = {}

    async def create_or_renegotiate(
        self,
        request: OfferRequest,
    ) -> tuple[OfferResponse, Any | None]:
        """Create or renegotiate a peer connection."""

        connection_cls, ice_server_cls, transport_cls, transport_params_cls = self._load_runtime()
        pc_id = request.pc_id
        created_transport: Any | None = None

        if pc_id and pc_id in self._peer_connections:
            connection = self._peer_connections[pc_id]
            await connection.renegotiate(
                sdp=request.sdp,
                type=request.type,
                restart_pc=request.restart_pc,
            )
        else:
            connection = connection_cls(
                [
                    ice_server_cls(
                        urls=server.urls,
                        username=server.username,
                        credential=server.credential,
                    )
                    for server in self._ice_servers
                ]
            )
            await connection.initialize(sdp=request.sdp, type=request.type)

            @connection.event_handler("closed")
            async def handle_closed(webrtc_connection: Any) -> None:
                log.info("peer_connection_closed", pc_id=webrtc_connection.pc_id)
                self._peer_connections.pop(webrtc_connection.pc_id, None)

            created_transport = transport_cls(
                webrtc_connection=connection,
                params=transport_params_cls(audio_in_enabled=True, audio_out_enabled=True),
            )

        answer = connection.get_answer()
        if not answer:
            raise SignalingRuntimeError("Failed to create WebRTC answer.")

        self._peer_connections[answer["pc_id"]] = connection
        return (
            OfferResponse(
                sessionId=request.session_id,
                sdp=answer["sdp"],
                type=answer["type"],
                pcId=answer["pc_id"],
            ),
            created_transport,
        )

    async def shutdown(self) -> None:
        """Disconnect all tracked peer connections."""

        for connection in list(self._peer_connections.values()):
            await connection.disconnect()
        self._peer_connections.clear()

    def get_runtime_status(self) -> tuple[bool, str | None]:
        """Return whether the SmallWebRTC runtime is importable."""

        try:
            self._load_runtime()
        except SignalingRuntimeError as exc:
            return False, str(exc)
        return True, None

    def _load_runtime(self) -> tuple[Any, Any, Any, Any]:
        try:
            from pipecat.transports.base_transport import TransportParams
            from pipecat.transports.smallwebrtc.connection import IceServer, SmallWebRTCConnection
            from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
        except ImportError as exc:
            raise SignalingRuntimeError(
                "Pipecat SmallWebRTC runtime is not installed. "
                "Install the optional `voice` dependencies for this package."
            ) from exc

        return SmallWebRTCConnection, IceServer, SmallWebRTCTransport, TransportParams
