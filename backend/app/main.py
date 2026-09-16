"""
Academix AI — FastAPI Application Entry Point

Main application factory with CORS, router registration, and health checks.
Run with: uvicorn app.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

# Fix for OpenMP runtime crash on Windows when loading embedding models
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from app.config import get_settings
from app.routers import auth, users, courses, classroom, scheduler, notices, rag


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan events.
    - Startup: initialize embedding model (loads into memory once)
    - Shutdown: cleanup resources
    """
    # --- Startup ---
    settings = get_settings()
    print(f"[*] {settings.APP_NAME} starting up...")
    print(f"   Environment: {settings.APP_ENV}")
    print(f"   Frontend URL: {settings.FRONTEND_URL}")

    # Pre-load the embedding model so first request isn't slow
    if settings.PRELOAD_EMBEDDING_MODEL:
        try:
            from app.services.rag.embeddings import get_embedding_model
            get_embedding_model()
            print(f"   [+] Embedding model loaded: {settings.EMBEDDING_MODEL}")
        except Exception as e:
            print(f"   [!] Embedding model failed to load: {e}")
            print(f"      RAG features will not work until this is resolved.")
    else:
        print("   [=] Embedding preload skipped (PRELOAD_EMBEDDING_MODEL=false)")

    yield

    # --- Shutdown ---
    print(f"[*] {settings.APP_NAME} shutting down...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        description="RAG-Powered Quiz Generation Platform for Academic Institutions",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # --- CORS Middleware ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            settings.FRONTEND_URL,
            "http://localhost:5173",  # Vite dev server
            "http://localhost:3000",  # Fallback
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Register Routers ---
    app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
    app.include_router(users.router, prefix="/api/users", tags=["Users"])
    app.include_router(courses.router, prefix="/api/courses", tags=["Courses"])
    app.include_router(classroom.router, prefix="/api/classroom", tags=["Classroom"])
    app.include_router(scheduler.router, prefix="/api/scheduler", tags=["Scheduler"])
    app.include_router(notices.router, prefix="/api/notices", tags=["Notice Board"])
    app.include_router(rag.router, prefix="/api/rag", tags=["RAG Engine"])

    # --- Health Check ---
    @app.get("/api/health", tags=["System"])
    async def health_check():
        return {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": "1.0.0",
            "environment": settings.APP_ENV,
        }

    return app


# Create the app instance
app = create_app()
