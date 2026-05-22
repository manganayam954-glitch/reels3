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
# Douyin (mobile amemv API — gives full metadata + multi-resolution formats)
# ---------------------------------------------------------------------------

DOUYIN_FEED = "https://api-hl.amemv.com/aweme/v1/feed/"
DOUYIN_UA = "com.ss.android.ugc.aweme/220400 (Linux; U; Android 11; en_US; SM-G973F; Build/RP1A.200720.012; Cronet/TTNetVersion:1.0.0.39 2020-08-17 QuicVersion:7e5b0b0)"


async def _douyin_resolve_aweme_id(client: httpx.AsyncClient, url: str) -> str | None:
    """Follow share links until we land on /share/video/{id} or /video/{id}."""

    import re as _re
    m = _re.search(r"/(?:share/)?video/(\d+)", url)
    if m:
        return m.group(1)
    try:
        r = await client.head(url, headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0)"}, follow_redirects=True)
        for resp in [r] + (r.history or []):
            for u in [str(resp.url), resp.headers.get("location", "")]:
                m = _re.search(r"/(?:share/)?video/(\d+)", u)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None


async def broker_douyin(client: httpx.AsyncClient, url: str, platform: Platform) -> BrokerResult:
    name = "douyin.amemv"
    try:
        aweme_id = await _douyin_resolve_aweme_id(client, url)
        if not aweme_id:
            return BrokerResult(False, name, error="couldn't resolve douyin aweme id")

        r = await client.get(DOUYIN_FEED, params={
            "aweme_id": aweme_id,
            "version_code": "22.4.0",
            "device_platform": "android",
            "aid": "1128",
        }, headers={"User-Agent": DOUYIN_UA})
        data = r.json()
        items = data.get("aweme_list") or []
        if not items:
            return BrokerResult(False, name, error="douyin returned empty feed")
        aw = items[0]

        title = (aw.get("desc") or "").strip() or None
        author = (aw.get("author") or {}).get("nickname")
        duration_ms = aw.get("duration") or 0
        cover_urls = (aw.get("video", {}).get("cover", {}) or {}).get("url_list") or []
        thumb = cover_urls[0] if cover_urls else None

        v = aw.get("video") or {}
        formats: list[VideoFormat] = []
        seen_urls: set[str] = set()
        seen_qualities: set[tuple[int, int]] = set()

        def _add(label: str, url: str | None, w: int, h: int, size: int | None = None) -> None:
            if not url or url in seen_urls:
                return
            seen_urls.add(url)
            key = (w, h)
            if key in seen_qualities and label != "Original":
                return
            seen_qualities.add(key)
            formats.append(VideoFormat(quality=label, url=url, ext="mp4", filesize=size))

        for br in v.get("bit_rate") or []:
            pa = br.get("play_addr") or {}
            urls = pa.get("url_list") or []
            if not urls:
                continue
            w, h = pa.get("width") or 0, pa.get("height") or 0
            label = f"{h}p" if h else (br.get("gear_name") or "auto")
            _add(label, urls[0], w, h, pa.get("data_size"))

        # download_addr is usually the original / highest quality (no watermark on Douyin).
        da = v.get("download_addr") or {}
        if da.get("url_list"):
            _add("Original", da["url_list"][0], da.get("width") or 0, da.get("height") or 0, da.get("data_size"))

        # Fallback: top-level play_addr if everything else missed.
        if not formats:
            pa = v.get("play_addr") or {}
            if pa.get("url_list"):
                _add("default", pa["url_list"][0], pa.get("width") or 0, pa.get("height") or 0, pa.get("data_size"))

        # Sort highest-quality first; "Original" wins ties.
        def _sort_key(f: VideoFormat) -> tuple[int, int]:
            q = f.quality
            if q == "Original":
                return (10_000, 1)
            digits = "".join(ch for ch in q if ch.isdigit())
            return (int(digits) if digits else 0, 0)

        formats.sort(key=_sort_key, reverse=True)

        if not formats:
            return BrokerResult(False, name, error="no video URLs found")
        return BrokerResult(
            True, name,
            title=title,
            thumbnail=thumb,
            duration=(duration_ms / 1000.0) if duration_ms else None,
            uploader=author,
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
    "douyin":    [broker_douyin, broker_loader],
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
