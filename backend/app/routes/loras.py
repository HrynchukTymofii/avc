"""GET /api/loras and DELETE /api/loras/{id}: the trained style registry."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_loras
from app.schemas import ErrorResponse, LorasResponse, LoraStyle
from app.services.auth import AuthUser, get_current_user, require_approved
from app.services.loras import LoraRegistry

router = APIRouter(prefix="/api", tags=["loras"])


@router.get("/loras", response_model=LorasResponse)
async def list_loras(
    registry: Annotated[LoraRegistry, Depends(get_loras)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> LorasResponse:
    return LorasResponse(
        loras=[
            LoraStyle(
                id=style.id,
                name=style.name,
                trigger=style.trigger,
                base=style.base,
                created_at=style.created_at,
            )
            for style in registry.list()
        ]
    )


@router.delete(
    "/loras/{lora_id}",
    status_code=204,
    responses={404: {"model": ErrorResponse}},
)
async def delete_lora(
    lora_id: str,
    registry: Annotated[LoraRegistry, Depends(get_loras)],
    user: Annotated[AuthUser, Depends(get_current_user)],
) -> None:
    require_approved(user)
    if not registry.delete(lora_id):
        raise HTTPException(status_code=404, detail="Style not found")
