from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

TELEGRAM_STICKER_SIZE = 512
TELEGRAM_STATIC_MAX_BYTES = 512 * 1024
TELEGRAM_VIDEO_MAX_BYTES = 256 * 1024
TELEGRAM_VIDEO_MAX_DURATION = 3
TELEGRAM_VIDEO_MAX_FPS = 30

_DEFAULT_WEBP_QUALITY = 90
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
    sticker_size: int = TELEGRAM_STICKER_SIZE
    webp_quality: int = _DEFAULT_WEBP_QUALITY
    static_max_bytes: int = TELEGRAM_STATIC_MAX_BYTES
    video_max_bytes: int = TELEGRAM_VIDEO_MAX_BYTES
    video_duration: int = TELEGRAM_VIDEO_MAX_DURATION
    video_fps: int = TELEGRAM_VIDEO_MAX_FPS
    video_min_crf: int = _DEFAULT_VIDEO_MIN_CRF
    video_max_crf: int = _DEFAULT_VIDEO_MAX_CRF
    video_crf_step: int = _DEFAULT_VIDEO_CRF_STEP
    ffmpeg_available: bool = False
    ffprobe_available: bool = False

    def __post_init__(self) -> None:
        if self.sticker_size != TELEGRAM_STICKER_SIZE:
            raise ValueError(f"STICKER_SIZE must be {TELEGRAM_STICKER_SIZE} for Telegram stickers")
        if not 1 <= self.webp_quality <= 100:
            raise ValueError("WEBP_QUALITY must be between 1 and 100")
        if not 1 <= self.static_max_bytes <= TELEGRAM_STATIC_MAX_BYTES:
            raise ValueError(f"STATIC_MAX_BYTES must be between 1 and {TELEGRAM_STATIC_MAX_BYTES}")
        if not 1 <= self.video_max_bytes <= TELEGRAM_VIDEO_MAX_BYTES:
            raise ValueError(f"VIDEO_MAX_BYTES must be between 1 and {TELEGRAM_VIDEO_MAX_BYTES}")
        if not 1 <= self.video_duration <= TELEGRAM_VIDEO_MAX_DURATION:
            raise ValueError(f"VIDEO_DURATION must be between 1 and {TELEGRAM_VIDEO_MAX_DURATION}")
        if not 1 <= self.video_fps <= TELEGRAM_VIDEO_MAX_FPS:
            raise ValueError(f"VIDEO_FPS must be between 1 and {TELEGRAM_VIDEO_MAX_FPS}")
        if not 0 <= self.video_min_crf <= 63:
            raise ValueError("VIDEO_MIN_CRF must be between 0 and 63")
        if not 0 <= self.video_max_crf <= 63:
            raise ValueError("VIDEO_MAX_CRF must be between 0 and 63")
        if self.video_min_crf > self.video_max_crf:
            raise ValueError("VIDEO_MIN_CRF must be <= VIDEO_MAX_CRF")
        if self.video_crf_step < 1:
            raise ValueError("VIDEO_CRF_STEP must be >= 1")

    @classmethod
    def from_env(cls) -> Config:
        token = (os.environ.get("BOT_TOKEN") or "").strip()
        if not token:
            raise SystemExit("BOT_TOKEN environment variable is required")
        return cls(
            bot_token=token,
            sticker_size=_env_int("STICKER_SIZE", TELEGRAM_STICKER_SIZE, min_value=TELEGRAM_STICKER_SIZE, max_value=TELEGRAM_STICKER_SIZE),
            webp_quality=_env_int("WEBP_QUALITY", _DEFAULT_WEBP_QUALITY, min_value=1, max_value=100),
            static_max_bytes=_env_int("STATIC_MAX_BYTES", TELEGRAM_STATIC_MAX_BYTES, min_value=1, max_value=TELEGRAM_STATIC_MAX_BYTES),
            video_max_bytes=_env_int("VIDEO_MAX_BYTES", TELEGRAM_VIDEO_MAX_BYTES, min_value=1, max_value=TELEGRAM_VIDEO_MAX_BYTES),
            video_duration=_env_int("VIDEO_DURATION", TELEGRAM_VIDEO_MAX_DURATION, min_value=1, max_value=TELEGRAM_VIDEO_MAX_DURATION),
            video_fps=_env_int("VIDEO_FPS", TELEGRAM_VIDEO_MAX_FPS, min_value=1, max_value=TELEGRAM_VIDEO_MAX_FPS),
            video_min_crf=_env_int("VIDEO_MIN_CRF", _DEFAULT_VIDEO_MIN_CRF, min_value=0, max_value=63),
            video_max_crf=_env_int("VIDEO_MAX_CRF", _DEFAULT_VIDEO_MAX_CRF, min_value=0, max_value=63),
            video_crf_step=_env_int("VIDEO_CRF_STEP", _DEFAULT_VIDEO_CRF_STEP, min_value=1),
            ffmpeg_available=shutil.which("ffmpeg") is not None,
            ffprobe_available=shutil.which("ffprobe") is not None,
        )
