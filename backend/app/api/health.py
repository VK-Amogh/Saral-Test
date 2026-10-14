"""Health check endpoint for Render monitoring and client warm-up."""

import time
from fastapi import APIRouter

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    """Public health endpoint returning operational status."""
    return {
        "status": "ok",
        "service": "saral-api",
        "version": "0.1.0",
        "timestamp": time.time(),
    }
