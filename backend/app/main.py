"""FastAPI application entrypoint with lifespan, CORS, and logging scrubber."""

from contextlib import asynccontextmanager
import logging
import sys
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.chat import router as chat_router
from .api.digilocker import router as digilocker_router
from .api.health import router as health_router
from .api.internal import router as internal_router
from .api.tasks import router as tasks_router
from .config import get_settings
from .scrubber import RedactingLogFilter


def setup_logging():
    """Attach RedactingLogFilter to root handlers to redact PII and secrets across all loggers."""
    settings = get_settings()
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Attach filter to all existing handlers
    redacting_filter = RedactingLogFilter()
    for handler in root_logger.handlers:
        handler.addFilter(redacting_filter)

    # If no handlers exist, configure standard StreamHandler with filter
    if not root_logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.addFilter(redacting_filter)
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"
        )
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager."""
    setup_logging()
    logging.info("Saral AI backend initialized and logging scrubber active.")
    yield
    logging.info("Saral AI backend shutting down.")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Saral AI API",
        description="Outcome-oriented Citizen Service Assistant Backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Custom HTTP error handler to preserve structured error/message dicts
    @app.exception_handler(HTTPException)
    async def custom_http_exception_handler(request: Request, exc: HTTPException):
        if isinstance(exc.detail, dict):
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "HTTP Error", "message": str(exc.detail)}
        )

    # Include route modules
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(tasks_router)
    app.include_router(internal_router)
    app.include_router(digilocker_router, prefix="/api/v1/digilocker")

    return app


app = create_app()
