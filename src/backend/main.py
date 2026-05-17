"""Main application module for the backend framework.

This module sets up (creates and configures) a FastAPI application:
    - Create FastAPI application instance.
    - Set up CORS middleware for cross-origin requests from local ports.
    - Register API routes for user authentication, jobs, and simulation.
    - Initialize database tables on application on startup.
    - Provide a health check endpoint for monitoring API status.

Attributes:
    app (FastAPI): FastAPI application instance.
    logger (logging.Logger): Logger instance for the module.

Usage:
    Run 'uvicorn' via 'uv' in production:

        $ uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000

    This will start the FastAPI server accessible on all network interfaces
    at port 8000.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from backend.routes import auth, jobs, sim
from db.models import Base
from db.session import engine

# Instantiate logger.
logger = logging.getLogger(__name__)

# Instantiate FastAPI application.
app = FastAPI()

# Add CORS middleware.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

# Register API routes.
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(sim.router)  # Will be removed eventually.


@app.on_event("startup")    # type: ignore[deprecated]
def on_startup():
    """Startup event handler.

    This function is triggered when the FastAPI application starts.
    It ensures that all database tables defined in the models are created.

    Raises:
        Exception: If creating the database tables fails.
    """
    logger.info("Starting up: creating database tables...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}", exc_info=True)
        raise


@app.get("/health")
async def health():
    """Health check endpoint.

    Returns a simple JSON response indicating that the API is running.

    Returns:
        dict: A dictionary containing the status of the API.
            Example:
                {"status": "ok"}
    """
    return {"status": "ok"}
