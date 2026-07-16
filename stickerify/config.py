from __future__ import annotations

import os
import shutil
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    sticker_size: int = 512
    webp_quality: int = 90
    animated_max_bytes: int = 256 * 1024
    animated_duration: int = 3
    animated_fps: int = 24
    ffmpeg_available: bool = False

    @classmethod
    def from_env(cls) -> Config:
        token = os.environ.get("BOT_TOKEN")
        if not token:
            raise SystemExit("BOT_TOKEN environment variable is required")
        return cls(
            bot_token=token,
            ffmpeg_available=shutil.which("ffmpeg") is not None,
        )
