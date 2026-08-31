"""Aggregate API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import documentation_jobs, health, repositories, stats

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(repositories.router)
api_router.include_router(documentation_jobs.router)
api_router.include_router(stats.router)
