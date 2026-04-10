"""HTTP signaling routes."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
import structlog

from voice_chess_server.api.dependencies import get_bot_orchestrator, get_signaling_service
from voice_chess_server.schemas.signaling import OfferRequest, OfferResponse
from voice_chess_server.services.orchestrator import BotOrchestrator
from voice_chess_server.services.signaling import (
    SignalingRuntimeError,
    SmallWebRTCSignalingService,
)

log = structlog.get_logger()
router = APIRouter(tags=["signaling"])


@router.post("/api/offer", response_model=OfferResponse)
async def create_offer(
    request: OfferRequest,
    background_tasks: BackgroundTasks,
    signaling_service: SmallWebRTCSignalingService = Depends(get_signaling_service),
    bot_orchestrator: BotOrchestrator = Depends(get_bot_orchestrator),
) -> OfferResponse:
    """Handle SmallWebRTC offer/answer exchange."""

    try:
        answer, transport = await signaling_service.create_or_renegotiate(request)
    except SignalingRuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if transport is not None:
        log.info("voice_transport_created", session_id=request.session_id)
        background_tasks.add_task(bot_orchestrator.run_transport, request.session_id, transport)

    return answer
