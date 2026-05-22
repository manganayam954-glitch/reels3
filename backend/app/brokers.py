"""Broker chain — third-party extractor APIs that handle bot-checks for us.

The free tier of every reel-downloader site eventually rate-limits, breaks, or
gets cloudflare-walled. We don't bet on a single one. Each platform has an
ordered list of brokers; we try them in order until one returns a playable
direct URL.

All brokers are public, anonymous, web-facing endpoints. We don't sign in,
don't pay, don't share user data. We're a thin proxy.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from app.schemas import Platform, VideoFormat

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class BrokerResult:
    ok: bool
    broker: str
    title: str | None = None
    thumbnail: str | None = None
    duration: float | None = None
    uploader: str | None = None
    formats: list[VideoFormat] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# loader.to (works for YouTube / Instagram / Facebook / TikTok)
# ---------------------------------------------------------------------------

LOADER_INIT = "https://loader.to/ajax/download.php"
LOADER_PROGRESS = "https://loader.to/ajax/progress.php"


async def broker_loader(client: httpx.AsyncClient, url: str, platform: Platform) -> BrokerResult:
    name = "loader.to"
    try:
        params = {"format": "720", "url": url}
        r = await client.get(LOADER_INIT, params=params, headers={
            "User-Agent": UA, "Referer": "https://loader.to/", "Accept": "application/json",
        })
        data = r.json()
        if not data.get("success") or not data.get("id"):
            return BrokerResult(False, name, error=data.get("message") or "init failed")

        job_id = data["id"]
        title = data.get("title") or data.get("info", {}).get("title")
        thumb = data.get("info", {}).get("image")
        # loader.to sometimes echoes the URL itself as the "title" — strip that.
        if title and (title.startswith("http://") or title.startswith("https://")):
            title = None

        for _ in range(40):
            await asyncio.sleep(2.5)
            pr = await client.get(LOADER_PROGRESS, params={"id": job_id}, headers={
                "User-Agent": UA, "Referer": "https://loader.to/",
            })
            pdata = pr.json()
            if pdata.get("download_url"):
                return BrokerResult(
                    True, name,
                    title=title, thumbnail=thumb,
                    formats=[VideoFormat(quality="720p", url=pdata["download_url"], ext="mp4")],
                )
            if pdata.get("text") and "error" in str(pdata.get("text", "")).lower():
                return BrokerResult(False, name, error=str(pdata.get("text")))
        return BrokerResult(False, name, error="timed out waiting for loader.to")
    except Exception as e:
        return BrokerResult(False, name, error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# tikwm.com (TikTok specialist — direct, no JS challenge)
# ---------------------------------------------------------------------------

async def broker_tikwm(client: httpx.AsyncClient, url: str, platform: Platform) -> BrokerResult:
    name = "tikwm.com"
    try:
        r = await client.get("https://www.tikwm.com/api/", params={"url": url}, headers={"User-Agent": UA})
        data = r.json()
        if data.get("code") != 0:
            return BrokerResult(False, name, error=data.get("msg") or "tikwm failed")
        d = data.get("data") or {}
        formats: list[VideoFormat] = []
        if d.get("hdplay"):
            formats.append(VideoFormat(quality="HD", url=d["hdplay"], ext="mp4", filesize=d.get("hd_size")))
        if d.get("play"):
            formats.append(VideoFormat(quality="SD (no watermark)", url=d["play"], ext="mp4", filesize=d.get("size")))
        if d.get("wmplay"):
            formats.append(VideoFormat(quality="SD (watermark)", url=d["wmplay"], ext="mp4", filesize=d.get("wm_size")))
        return BrokerResult(
            True, name,
            title=d.get("title"),
            thumbnail=d.get("cover") or d.get("origin_cover"),
            duration=float(d["duration"]) if d.get("duration") else None,
            uploader=(d.get("author") or {}).get("nickname") if isinstance(d.get("author"), dict) else d.get("author"),
            formats=formats,
        )
    except Exception as e:
        return BrokerResult(False, name, error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# snapsave.app (Facebook + Instagram fallback)
# ---------------------------------------------------------------------------

SNAPSAVE_DECODER_JS = Path(__file__).resolve().parent.parent / "scripts" / "snapsave_decode.js"


async def broker_snapsave(client: httpx.AsyncClient, url: str, platform: Platform) -> BrokerResult:
    name = "snapsave.app"
    if not SNAPSAVE_DECODER_JS.exists():
        return BrokerResult(False, name, error="snapsave decoder script missing")
    try:
        # Run the node decoder out-of-process. It does the request + JS unpack.
        proc = await asyncio.create_subprocess_exec(
            "node", str(SNAPSAVE_DECODER_JS), url,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            return BrokerResult(False, name, error="snapsave decoder timed out")
        if proc.returncode != 0:
            return BrokerResult(False, name, error=stderr.decode(errors="replace")[:200])
        data = json.loads(stdout.decode())
        if not data.get("href_urls"):
            return BrokerResult(False, name, error="snapsave returned no urls")
        formats = [
            VideoFormat(quality=f"link {i+1}", url=u, ext="mp4")
            for i, u in enumerate(data["href_urls"][:4])
        ]
        return BrokerResult(
            True, name,
            title=data.get("title"),
            thumbnail=data.get("thumbnail"),
            formats=formats,
        )
    except Exception as e:
        return BrokerResult(False, name, error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Chain registry
# ---------------------------------------------------------------------------

_CHAINS: dict[Platform, list[Callable[..., Awaitable[BrokerResult]]]] = {
    "youtube":   [broker_loader],
    "instagram": [broker_loader, broker_snapsave],
    "facebook":  [broker_snapsave, broker_loader],
    "tiktok":    [broker_tikwm, broker_loader],
}


async def run_chain(url: str, platform: Platform) -> BrokerResult:
    """Try each broker in order. Return the first success, or the last error."""

    chain = _CHAINS.get(platform)
    if not chain:
        return BrokerResult(False, "none", error=f"platform {platform!r} not supported")

    timeout = httpx.Timeout(30.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        last: BrokerResult | None = None
        for fn in chain:
            logger.info("Trying broker %s for %s", fn.__name__, platform)
            res = await fn(client, url, platform)
            if res.ok:
                return res
            logger.info("Broker %s failed: %s", fn.__name__, res.error)
            last = res
        return last or BrokerResult(False, "none", error="all brokers failed")
