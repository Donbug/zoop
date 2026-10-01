"""ASGI entrypoint: ``uvicorn zoop_bff.main:app --port 8787`` (configured via ZOOP_* env vars)."""

from .app import create_app

app = create_app()
