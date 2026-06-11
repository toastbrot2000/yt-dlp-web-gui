"""Request bodies for the API endpoints."""

from typing import Literal

from pydantic import BaseModel, field_validator


class DownloadRequest(BaseModel):
    url: str
    format_type: Literal["mp4", "mp3"]
    # "best" or any probed height; validated so nothing else can be injected
    # into yt-dlp's format selector
    quality: str = "best"

    @field_validator("quality")
    @classmethod
    def validate_quality(cls, v: str) -> str:
        if v == "best":
            return v
        if v.isdigit() and 144 <= int(v) <= 4320:
            return v
        raise ValueError("quality must be 'best' or a video height between 144 and 4320")


class FormatsRequest(BaseModel):
    url: str
