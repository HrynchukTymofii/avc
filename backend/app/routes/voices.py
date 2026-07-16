"""GET /api/voices."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.schemas import VoicesResponse
from app.services.auth import AuthUser, get_current_user
from app.services.voices import VoiceRegistry

router = APIRouter(prefix="/api", tags=["voices"])


def get_voices(request: Request) -> VoiceRegistry:
    return request.app.state.voices


@router.get("/voices", response_model=VoicesResponse)
async def list_voices(
    registry: Annotated[VoiceRegistry, Depends(get_voices)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> VoicesResponse:
    return VoicesResponse(voices=registry.voices)
