"""HTTP signaling schemas."""

from pydantic import BaseModel, ConfigDict, Field


class OfferRequest(BaseModel):
    """Incoming WebRTC offer request."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(alias="sessionId", min_length=1)
    sdp: str = Field(min_length=1)
    type: str = Field(min_length=1)
    pc_id: str | None = Field(default=None, alias="pcId")
    restart_pc: bool = Field(default=False, alias="restartPc")


class OfferResponse(BaseModel):
    """WebRTC answer response."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(alias="sessionId", min_length=1)
    sdp: str = Field(min_length=1)
    type: str = Field(min_length=1)
    pc_id: str = Field(alias="pcId", min_length=1)
