from fastapi import FastAPI

from app.api.v1.router import router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging(get_settings().log_level)
app = FastAPI(title="Engine Oil Compatibility API", version="0.1.0")
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
