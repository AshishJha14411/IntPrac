"""v1 API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, bank, documents, health, reports, sessions

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(documents.router)
api_router.include_router(sessions.router)
api_router.include_router(reports.router)
api_router.include_router(bank.router)
