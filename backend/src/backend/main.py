from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import Settings

settings = Settings()

app = FastAPI(title="MedulaAPI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(origin).rstrip("/") for origin in settings.cors_allowed_origins],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=[],
)


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok"}
