from fastapi import APIRouter

from app.api.routes import health, session, realtime, focus


api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(session.router, prefix="/session", tags=["session"])
api_router.include_router(realtime.router, prefix="/session", tags=["realtime"])
api_router.include_router(focus.router, prefix="/focus", tags=["focus"])

__all__ = ["api_router"]

