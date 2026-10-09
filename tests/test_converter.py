from __future__ import annotations

import io
import json
import subprocess

from PIL import Image

from stickerify.config import Config
from stickerify.converter import MediaToolError, StickerConverter


def _bytes_buffer(payload: bytes) -> io.BytesIO:
    buf = io.BytesIO(payload)
    buf.seek(0)
    return buf


def _valid_probe_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "vp9",
                "width": 512,
                "height": 512,
                "duration": "2.0",
                "avg_frame_rate": "30/1",
            }
        ],
        "format": {"format_name": "matroska,webm", "duration": "2.0"},
    }
    payload.update(overrides)
    return payload


def test_convert_resizes_longest_side_to_config_size() -> None:
    converter = StickerConverter(Config(bot_token="token"))
    img = Image.new("RGB", (1000, 500), "red")

    result = converter.convert_static(img)

    assert result.ok
    assert result.warnings == ()
    assert result.png is not None
    assert result.webp is not None
    out_png = Image.open(result.png)
    out_webp = Image.open(result.webp)
    assert out_png.size == (512, 256)
    assert out_webp.size == (512, 256)
    assert out_png.format == "PNG"
    assert out_webp.format == "WEBP"


def test_convert_static_skips_oversized_png_and_retries_webp(monkeypatch) -> None:
    converter = StickerConverter(Config(bot_token="token", static_max_bytes=5, webp_quality=90))
    img = Image.new("RGB", (512, 512), "red")

    def fake_to_buffer(_img: Image.Image, fmt: str, **kwargs: int | bool) -> io.BytesIO:
        if fmt == "PNG":
            return _bytes_buffer(b"too-large")
        quality = kwargs.get("quality")
        return _bytes_buffer(b"too-large") if quality == 90 else _bytes_buffer(b"ok")

    monkeypatch.setattr(StickerConverter, "_to_buffer", staticmethod(fake_to_buffer))

    result = converter.convert_static(img)

    assert result.png is None
    assert result.webp is not None
    assert result.webp.getvalue() == b"ok"
    assert any("PNG output is larger" in warning for warning in result.warnings)
    assert any("WebP quality lowered" in warning for warning in result.warnings)


def test_to_video_sticker_returns_reason_without_ffmpeg() -> None:
    converter = StickerConverter(Config(bot_token="token", ffmpeg_available=False))

    result = converter.to_video_sticker(b"gif data")

    assert not result.ok
    assert result.reason == "FFmpeg is not installed"


def test_to_video_sticker_requires_ffprobe() -> None:
    converter = StickerConverter(Config(bot_token="token", ffmpeg_available=True, ffprobe_available=False))

    result = converter.to_video_sticker(b"gif data")

    assert not result.ok
    assert result.reason == "FFprobe is required to verify video stickers"


def test_validate_video_sticker_rejects_oversized_output(tmp_path) -> None:
    converter = StickerConverter(
        Config(bot_token="token", video_max_bytes=4, ffmpeg_available=True, ffprobe_available=True)
    )
    output = tmp_path / "video.webm"
    output.write_bytes(b"12345")

    valid, reason = converter._validate_video_sticker(str(output))

    assert valid is False
    assert "too large" in reason


def test_validate_video_sticker_rejects_missing_ffprobe(tmp_path, monkeypatch) -> None:
    converter = StickerConverter(Config(bot_token="token", ffmpeg_available=True, ffprobe_available=True))
    output = tmp_path / "video.webm"
    output.write_bytes(b"ok")
    monkeypatch.setattr("stickerify.converter.shutil.which", lambda _: None)

    valid, reason = converter._validate_video_sticker(str(output))

    assert valid is False
    assert reason == "FFprobe is required to verify video stickers"


def test_validate_video_sticker_accepts_valid_ffprobe_payload(tmp_path, monkeypatch) -> None:
    converter = StickerConverter(Config(bot_token="token", ffmpeg_available=True, ffprobe_available=True))
    output = tmp_path / "video.webm"
    output.write_bytes(b"ok")
    monkeypatch.setattr("stickerify.converter.shutil.which", lambda _: "/usr/bin/ffprobe")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(_valid_probe_payload()), stderr="")

    monkeypatch.setattr("stickerify.converter.subprocess.run", fake_run)

    valid, reason = converter._validate_video_sticker(str(output))

    assert valid is True
    assert reason == ""


def test_validate_probe_payload_rejects_invalid_video_properties() -> None:
    converter = StickerConverter(Config(bot_token="token", ffmpeg_available=True, ffprobe_available=True))

    cases = [
        ({"streams": [{"codec_type": "video", "codec_name": "h264", "width": 512, "height": 512}]}, "not VP9"),
        (_valid_probe_payload(streams=[{"codec_type": "audio", "codec_name": "opus"}]), "exactly one video"),
        (
            _valid_probe_payload(
                streams=[
                    {
                        "codec_type": "video",
                        "codec_name": "vp9",
                        "width": 512,
                        "height": 512,
                        "duration": "2.0",
                        "avg_frame_rate": "30/1",
                    },
                    {"codec_type": "audio", "codec_name": "opus"},
                ]
            ),
            "must not contain audio",
        ),
        (_valid_probe_payload(streams=[{"codec_type": "video", "codec_name": "vp9", "width": 600, "height": 512}]), "512x512"),
        (_valid_probe_payload(format={"format_name": "mp4", "duration": "2.0"}), "container"),
        (_valid_probe_payload(format={"format_name": "matroska,webm", "duration": "4.0"}), "longer"),
        (
            _valid_probe_payload(
                streams=[
                    {
                        "codec_type": "video",
                        "codec_name": "vp9",
                        "width": 512,
                        "height": 512,
                        "duration": "2.0",
                        "avg_frame_rate": "31/1",
                    }
                ]
            ),
            "frame rate",
        ),
    ]

    for payload, expected in cases:
        valid, reason = converter._validate_probe_payload(payload)
        assert valid is False
        assert expected in reason


def test_to_video_sticker_invokes_ffmpeg_with_vp9_webm_args(monkeypatch) -> None:
    converter = StickerConverter(
        Config(
            bot_token="token",
            video_max_bytes=1024,
            video_min_crf=36,
            video_max_crf=36,
            ffmpeg_available=True,
            ffprobe_available=True,
        )
    )
    calls: list[list[str]] = []

    def fake_run_ffmpeg(args: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        output = args[-1]
        assert output.endswith(".webm")
        with open(output, "wb") as f:
            f.write(b"webm")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(StickerConverter, "_run_ffmpeg", staticmethod(fake_run_ffmpeg))
    monkeypatch.setattr(StickerConverter, "_validate_video_sticker", lambda self, path: (True, ""))

    result = converter.to_video_sticker(b"video data")

    assert result.ok
    assert result.buffer is not None
    assert result.buffer.getvalue() == b"webm"
    args = calls[0]
    assert "-an" in args
    assert args[args.index("-c:v") + 1] == "libvpx-vp9"
    assert args[args.index("-crf") + 1] == "36"
    assert args[args.index("-vf") + 1].startswith("format=rgba")
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
            ffprobe_available=True,
        )
    )
    crfs: list[str] = []

    def fake_run_ffmpeg(args: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
        crf = args[args.index("-crf") + 1]
        crfs.append(crf)
        output = args[-1]
        payload = b"too-large" if crf == "36" else b"ok"
        with open(output, "wb") as f:
            f.write(payload)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(StickerConverter, "_run_ffmpeg", staticmethod(fake_run_ffmpeg))
    monkeypatch.setattr(
        StickerConverter,
        "_validate_video_sticker",
        lambda self, path: (path.endswith("crf40.webm"), "WEBM output is too large for Telegram video sticker limits"),
    )

    result = converter.to_video_sticker(b"video data")

    assert result.ok
    assert result.buffer is not None
    assert result.buffer.getvalue() == b"ok"
    assert crfs == ["36", "40"]


def test_run_ffmpeg_raises_safe_error(monkeypatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, 1, stderr=b"/tmp/private/path: scary internal stderr")

    monkeypatch.setattr("stickerify.converter.subprocess.run", fake_run)

    try:
        StickerConverter._run_ffmpeg(["-version"], timeout=1)
    except MediaToolError as exc:
        assert str(exc) == "FFmpeg failed to process this media"
        assert "private/path" in exc.stderr
    else:
        raise AssertionError("MediaToolError was not raised")


def test_to_png_preserves_original_dimensions() -> None:
    converter = StickerConverter(Config(bot_token="token"))
    img = Image.new("RGB", (123, 45), "blue")

    png = converter.to_png(img)

    out = Image.open(io.BytesIO(png.getvalue()))
    assert out.size == (123, 45)
    assert out.format == "PNG"
