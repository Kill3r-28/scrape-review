"""Public entry: proxy to the ticket app when live, else show offline page."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

APP_INTERNAL_URL = os.getenv("APP_INTERNAL_URL", "http://127.0.0.1:8001").rstrip("/")
STATIC_DIR = Path(__file__).parent / "static"
OFFLINE_HTML = (STATIC_DIR / "offline.html").read_text(encoding="utf-8")

app = FastAPI(title="SME Ticket Gatekeeper", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)


async def app_is_live() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{APP_INTERNAL_URL}/health")
            return response.status_code == 200
    except httpx.HTTPError:
        return False


def offline_response() -> HTMLResponse:
    return HTMLResponse(OFFLINE_HTML, status_code=503)


@app.get("/health")
async def health():
    if await app_is_live():
        return {"status": "ok", "app": "live"}
    return {"status": "offline", "app": "down"}


@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def proxy(request: Request, full_path: str = ""):
    if not await app_is_live():
        return offline_response()

    target = f"{APP_INTERNAL_URL}/{full_path}" if full_path else f"{APP_INTERNAL_URL}/"
    if request.url.query:
        target = f"{target}?{request.url.query}"

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP and key.lower() != "host"
    }
    body = await request.body()

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=False) as client:
        upstream = await client.request(
            request.method,
            target,
            headers=headers,
            content=body,
        )

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in HOP_BY_HOP
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )
