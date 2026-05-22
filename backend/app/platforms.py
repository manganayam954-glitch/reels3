"""Platform detection from URLs."""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from app.schemas import Platform

_HOSTS: dict[Platform, tuple[str, ...]] = {
    "youtube": ("youtube.com", "youtu.be", "m.youtube.com", "youtube-nocookie.com"),
    "instagram": ("instagram.com", "instagr.am"),
    "facebook": ("facebook.com", "fb.watch", "fb.com", "m.facebook.com"),
    "tiktok": ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com", "m.tiktok.com"),
    "douyin": ("douyin.com", "v.douyin.com", "iesdouyin.com"),
}


def normalize_url(url: str) -> str:
    """Strip mobile/share wrappers."""

    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")

    if host in {"l.facebook.com", "lm.facebook.com"}:
        target = parse_qs(parsed.query).get("u", [None])[0]
        if target:
            return unquote(target)

    if host == "youtube.com" and parsed.path == "/redirect":
        target = parse_qs(parsed.query).get("q", [None])[0]
        if target:
            return unquote(target)

    return url.strip()


def detect_platform(url: str) -> Platform:
    """Return canonical platform for a URL."""

    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return "other"
    host = host.removeprefix("www.")
    for platform, hosts in _HOSTS.items():
        if any(host == h or host.endswith(f".{h}") for h in hosts):
            return platform
    return "other"
