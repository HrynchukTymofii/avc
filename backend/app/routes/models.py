"""GET /api/models: the engine catalog per job kind, with availability."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import Settings
from app.deps import get_settings_dep
from app.models_catalog import engines_for, is_available
from app.schemas import EngineInfo, JobKind, ModelsResponse
from app.services.auth import AuthUser, get_current_user

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/models", response_model=ModelsResponse)
async def list_models(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    _user: Annotated[AuthUser, Depends(get_current_user)],
) -> ModelsResponse:
    return ModelsResponse(
        models={
            kind.value: [
                EngineInfo(
                    id=engine.id,
                    label=engine.label,
                    tier=engine.tier,  # type: ignore[arg-type]
                    credits=engine.credits,
                    available=is_available(engine, settings),
                    default=engine.default,
                )
                for engine in engines_for(kind)
            ]
            for kind in JobKind
        }
    )
