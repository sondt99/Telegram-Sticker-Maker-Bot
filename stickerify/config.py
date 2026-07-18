from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

_DEFAULT_STICKER_SIZE = 512
_DEFAULT_WEBP_QUALITY = 90
_DEFAULT_VIDEO_MAX_BYTES = 256 * 1024
_DEFAULT_VIDEO_DURATION = 3
_DEFAULT_VIDEO_FPS = 30
_DEFAULT_VIDEO_MIN_CRF = 36
_DEFAULT_VIDEO_MAX_CRF = 48
_DEFAULT_VIDEO_CRF_STEP = 4


def _env_int(name: str, default: int, *, min_value: int, max_value: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer") from exc
    if value < min_value:
        raise SystemExit(f"{name} must be >= {min_value}")
    if max_value is not None and value > max_value:
        raise SystemExit(f"{name} must be <= {max_value}")
    return value


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    sticker_size: int = _DEFAULT_STICKER_SIZE
    webp_quality: int = _DEFAULT_WEBP_QUALITY
    video_max_bytes: int = _DEFAULT_VIDEO_MAX_BYTES
    video_duration: int = _DEFAULT_VIDEO_DURATION
    video_fps: int = _DEFAULT_VIDEO_FPS
    video_min_crf: int = _DEFAULT_VIDEO_MIN_CRF
    video_max_crf: int = _DEFAULT_VIDEO_MAX_CRF
    video_crf_step: int = _DEFAULT_VIDEO_CRF_STEP
    ffmpeg_available: bool = False

    def __post_init__(self) -> None:
        if self.video_min_crf > self.video_max_crf:
            raise ValueError("VIDEO_MIN_CRF must be <= VIDEO_MAX_CRF")

    @classmethod
    def from_env(cls) -> Config:
        token = os.environ.get("BOT_TOKEN")
        if not token:
            raise SystemExit("BOT_TOKEN environment variable is required")
        return cls(
            bot_token=token,
            sticker_size=_env_int("STICKER_SIZE", _DEFAULT_STICKER_SIZE, min_value=1),
            webp_quality=_env_int("WEBP_QUALITY", _DEFAULT_WEBP_QUALITY, min_value=1, max_value=100),
            video_max_bytes=_env_int("VIDEO_MAX_BYTES", _DEFAULT_VIDEO_MAX_BYTES, min_value=1),
            video_duration=_env_int("VIDEO_DURATION", _DEFAULT_VIDEO_DURATION, min_value=1),
            video_fps=_env_int("VIDEO_FPS", _DEFAULT_VIDEO_FPS, min_value=1),
            video_min_crf=_env_int("VIDEO_MIN_CRF", _DEFAULT_VIDEO_MIN_CRF, min_value=0, max_value=63),
            video_max_crf=_env_int("VIDEO_MAX_CRF", _DEFAULT_VIDEO_MAX_CRF, min_value=0, max_value=63),
            video_crf_step=_env_int("VIDEO_CRF_STEP", _DEFAULT_VIDEO_CRF_STEP, min_value=1),
            ffmpeg_available=shutil.which("ffmpeg") is not None,
        )
