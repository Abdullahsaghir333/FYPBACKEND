from typing import Dict

from fastapi import APIRouter


router = APIRouter()


@router.get("/health", summary="Health check")
async def health() -> Dict[str, str]:
    return {"status": "ok"}

