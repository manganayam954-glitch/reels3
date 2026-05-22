"""Pydantic models for the API surface."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Platform = Literal["youtube", "instagram", "facebook", "tiktok", "douyin", "other"]


class ExtractRequest(BaseModel):
    url: str = Field(..., min_length=4)


class VideoFormat(BaseModel):
    quality: str
    url: str
    ext: str = "mp4"
    filesize: Optional[int] = None


class ExtractResponse(BaseModel):
    ok: bool
    platform: Platform
    title: Optional[str] = None
    thumbnail: Optional[str] = None
    duration: Optional[float] = None
    uploader: Optional[str] = None
    formats: list[VideoFormat] = Field(default_factory=list)
    best_url: Optional[str] = None
    broker: Optional[str] = None
    error: Optional[str] = None
