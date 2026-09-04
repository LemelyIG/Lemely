"""Meta / health endpoints under ``/api``."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lemely.runtime.config import Settings
from lemely.web.deps import get_settings
from lemely.web.schemas import HealthDTO, StorageHealthDTO

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthDTO)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthDTO:
    """Return service health and whether a Gemini API key is configured."""
    return HealthDTO(
        apiKeyConfigured=settings.gemini_api_key is not None,
        storage=StorageHealthDTO(backend=settings.storage.backend, bucket=settings.storage.bucket),
    )
