from __future__ import annotations

import pytest

from stickerify.config import Config


_ENV_KEYS = (
    "BOT_TOKEN",
    "STICKER_SIZE",
    "WEBP_QUALITY",
    "VIDEO_MAX_BYTES",
    "VIDEO_DURATION",
    "VIDEO_FPS",
    "VIDEO_MIN_CRF",
    "VIDEO_MAX_CRF",
    "VIDEO_CRF_STEP",
)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_from_env_requires_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)

    with pytest.raises(SystemExit, match="BOT_TOKEN"):
        Config.from_env()


def test_from_env_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setattr("stickerify.config.shutil.which", lambda _: None)

    config = Config.from_env()

    assert config.bot_token == "token"
    assert config.sticker_size == 512
    assert config.webp_quality == 90
    assert config.video_max_bytes == 256 * 1024
    assert config.video_duration == 3
    assert config.video_fps == 30
    assert config.video_min_crf == 36
    assert config.video_max_crf == 48
    assert config.video_crf_step == 4
    assert config.ffmpeg_available is False


def test_from_env_reads_media_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("STICKER_SIZE", "256")
    monkeypatch.setenv("WEBP_QUALITY", "80")
    monkeypatch.setenv("VIDEO_MAX_BYTES", "131072")
    monkeypatch.setenv("VIDEO_DURATION", "2")
    monkeypatch.setenv("VIDEO_FPS", "18")
    monkeypatch.setenv("VIDEO_MIN_CRF", "40")
    monkeypatch.setenv("VIDEO_MAX_CRF", "52")
    monkeypatch.setenv("VIDEO_CRF_STEP", "6")
    monkeypatch.setattr("stickerify.config.shutil.which", lambda _: "/usr/bin/ffmpeg")

    config = Config.from_env()

    assert config.sticker_size == 256
    assert config.webp_quality == 80
    assert config.video_max_bytes == 131072
    assert config.video_duration == 2
    assert config.video_fps == 18
    assert config.video_min_crf == 40
    assert config.video_max_crf == 52
    assert config.video_crf_step == 6
    assert config.ffmpeg_available is True


def test_from_env_rejects_invalid_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("VIDEO_FPS", "fast")

    with pytest.raises(SystemExit, match="VIDEO_FPS must be an integer"):
        Config.from_env()


def test_config_rejects_invalid_crf_range() -> None:
    with pytest.raises(ValueError, match="VIDEO_MIN_CRF"):
        Config(bot_token="token", video_min_crf=50, video_max_crf=40)
