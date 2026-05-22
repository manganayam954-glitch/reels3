"""FastAPI entrypoint."""

from __future__ import annotations

import logging
import urllib.parse
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.brokers import UA, run_chain
from app.platforms import detect_platform, normalize_url
from app.schemas import ExtractRequest, ExtractResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("reels3")

app = FastAPI(title="reels3", description="Multi-platform Reels downloader")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/extract", response_model=ExtractResponse)
async def extract(req: ExtractRequest) -> ExtractResponse:
    url = normalize_url(req.url)
    platform = detect_platform(url)
    if platform == "other":
        return ExtractResponse(
            ok=False,
            platform=platform,
            error="URL platform not supported. We handle YouTube, Instagram, Facebook, TikTok.",
        )
    res = await run_chain(url, platform)
    return ExtractResponse(
        ok=res.ok,
        platform=platform,
        title=res.title,
        thumbnail=res.thumbnail,
        duration=res.duration,
        uploader=res.uploader,
        formats=res.formats,
        best_url=res.formats[0].url if res.formats else None,
        broker=res.broker,
        error=res.error,
    )


@app.get("/api/download")
async def download_proxy(
    url: str = Query(..., description="Direct media URL to proxy"),
    filename: str = Query("video.mp4"),
) -> StreamingResponse:
    """Stream a direct media URL through us so the browser can save it without
    hitting CORS or referer issues."""

    safe_filename = filename.replace('"', "").replace("\n", "").replace("\r", "")[:200]

    async def iterate() -> AsyncIterator[bytes]:
        timeout = httpx.Timeout(60.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                async with client.stream("GET", url, headers={"User-Agent": UA}) as resp:
                    if resp.status_code >= 400:
                        logger.warning("Upstream %s returned %s", url, resp.status_code)
                        return
                    async for chunk in resp.aiter_bytes(64 * 1024):
                        yield chunk
            except Exception:
                logger.exception("Proxy download failed for %s", url)

    return StreamingResponse(
        iterate(),
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


# Serve frontend if mounted alongside (single-container deploy on Render).
_FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
if _FRONTEND.is_dir():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(str(_FRONTEND / "index.html"))
