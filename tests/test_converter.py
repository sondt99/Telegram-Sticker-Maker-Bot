from __future__ import annotations

import io
import subprocess

from PIL import Image

from stickerify.config import Config
from stickerify.converter import StickerConverter


def test_convert_resizes_longest_side_to_config_size() -> None:
    converter = StickerConverter(Config(bot_token="token", sticker_size=512))
    img = Image.new("RGB", (1000, 500), "red")

    png, webp = converter.convert(img)

    out_png = Image.open(png)
    out_webp = Image.open(webp)
    assert out_png.size == (512, 256)
    assert out_webp.size == (512, 256)
    assert out_png.format == "PNG"
    assert out_webp.format == "WEBP"


def test_to_video_sticker_returns_reason_without_ffmpeg() -> None:
    converter = StickerConverter(Config(bot_token="token", ffmpeg_available=False))

    result = converter.to_video_sticker(b"gif data")

    assert not result.ok
    assert result.reason == "FFmpeg is not installed"


def test_validate_video_sticker_rejects_oversized_output(tmp_path, monkeypatch) -> None:
    converter = StickerConverter(Config(bot_token="token", video_max_bytes=4, ffmpeg_available=True))
    output = tmp_path / "video.webm"
    output.write_bytes(b"12345")
    monkeypatch.setattr("stickerify.converter.shutil.which", lambda _: None)

    valid, reason = converter._validate_video_sticker(str(output))

    assert valid is False
    assert "too large" in reason


def test_to_video_sticker_invokes_ffmpeg_with_vp9_webm_args(monkeypatch) -> None:
    converter = StickerConverter(
        Config(
            bot_token="token",
            video_max_bytes=1024,
            video_min_crf=36,
            video_max_crf=36,
            ffmpeg_available=True,
        )
    )
    calls: list[list[str]] = []
    monkeypatch.setattr("stickerify.converter.shutil.which", lambda _: None)

    def fake_run_ffmpeg(args: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        output = args[-1]
        assert output.endswith(".webm")
        with open(output, "wb") as f:
            f.write(b"webm")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(StickerConverter, "_run_ffmpeg", staticmethod(fake_run_ffmpeg))

    result = converter.to_video_sticker(b"video data")

    assert result.ok
    assert result.buffer is not None
    assert result.buffer.getvalue() == b"webm"
    args = calls[0]
    assert "-an" in args
    assert args[args.index("-c:v") + 1] == "libvpx-vp9"
    assert args[args.index("-crf") + 1] == "36"
    assert args[-1].endswith(".webm")


def test_to_video_sticker_retries_until_output_fits(monkeypatch) -> None:
    converter = StickerConverter(
        Config(
            bot_token="token",
            video_max_bytes=4,
            video_min_crf=36,
            video_max_crf=40,
            video_crf_step=4,
            ffmpeg_available=True,
        )
    )
    crfs: list[str] = []
    monkeypatch.setattr("stickerify.converter.shutil.which", lambda _: None)

    def fake_run_ffmpeg(args: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
        crf = args[args.index("-crf") + 1]
        crfs.append(crf)
        output = args[-1]
        payload = b"too-large" if crf == "36" else b"ok"
        with open(output, "wb") as f:
            f.write(payload)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(StickerConverter, "_run_ffmpeg", staticmethod(fake_run_ffmpeg))

    result = converter.to_video_sticker(b"video data")

    assert result.ok
    assert result.buffer is not None
    assert result.buffer.getvalue() == b"ok"
    assert crfs == ["36", "40"]


def test_to_png_preserves_original_dimensions() -> None:
    converter = StickerConverter(Config(bot_token="token"))
    img = Image.new("RGB", (123, 45), "blue")

    png = converter.to_png(img)

    out = Image.open(io.BytesIO(png.getvalue()))
    assert out.size == (123, 45)
    assert out.format == "PNG"
