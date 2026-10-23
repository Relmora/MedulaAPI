from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.auth.routes import router as auth_router
from backend.config import Settings
from backend.errors import install_error_handlers
from backend.knowledge_bases.routes import router as knowledge_base_router
from backend.logging import configure_logging
from backend.middleware import RequestLoggingMiddleware
from backend.workspaces.routes import router as workspace_router

settings = Settings()
configure_logging(settings.log_level)

app = FastAPI(title="MedulaAPI", version="0.1.0")
install_error_handlers(app)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(origin).rstrip("/") for origin in settings.cors_allowed_origins],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
    expose_headers=["X-Request-ID"],
)


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(workspace_router)

app.include_router(knowledge_base_router)
