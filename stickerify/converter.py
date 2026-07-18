from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .config import Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VideoStickerResult:
    buffer: io.BytesIO | None
    size_bytes: int | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.buffer is not None


class StickerConverter:
    __slots__ = (
        "_size",
        "_quality",
        "_video_max_bytes",
        "_video_duration",
        "_video_fps",
        "_video_min_crf",
        "_video_max_crf",
        "_video_crf_step",
        "_has_ffmpeg",
    )

    def __init__(self, config: Config) -> None:
        self._size = config.sticker_size
        self._quality = config.webp_quality
        self._video_max_bytes = config.video_max_bytes
        self._video_duration = config.video_duration
        self._video_fps = config.video_fps
        self._video_min_crf = config.video_min_crf
        self._video_max_crf = config.video_max_crf
        self._video_crf_step = config.video_crf_step
        self._has_ffmpeg = config.ffmpeg_available

    @property
    def has_ffmpeg(self) -> bool:
        return self._has_ffmpeg

    def convert(self, img: Image.Image, *, remove_bg: bool = False) -> tuple[io.BytesIO, io.BytesIO]:
        if remove_bg:
            img = self.remove_background(img)
        img = self._resize(img.convert("RGBA"))
        return self._to_buffer(img, "PNG"), self._to_buffer(img, "WEBP", quality=self._quality)

    def extract_frame(self, data: bytes, *, middle: bool = False) -> Image.Image | None:
        if not self._has_ffmpeg:
            return None
        return self._ffmpeg_extract(data, middle=middle)

    def to_video_sticker(self, data: bytes) -> VideoStickerResult:
        if not self._has_ffmpeg:
            return VideoStickerResult(None, reason="FFmpeg is not installed")
        return self._ffmpeg_video_sticker(data)

    @staticmethod
    def remove_background(img: Image.Image) -> Image.Image:
        from rembg import remove
        return remove(img)

    def to_png(self, img: Image.Image) -> io.BytesIO:
        return self._to_buffer(img.convert("RGBA"), "PNG")

    def extract_frame_original(self, data: bytes) -> Image.Image | None:
        if not self._has_ffmpeg:
            return None
        src = self._write_temp(data, ".webm")
        dst = src + ".png"
        try:
            self._run_ffmpeg(["-i", src, "-frames:v", "1", dst], timeout=30)
            return Image.open(dst).copy() if os.path.exists(dst) else None
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Original frame extraction failed: %s", exc)
            return None
        finally:
            self._cleanup(src, dst)

    def _resize(self, img: Image.Image) -> Image.Image:
        w, h = img.size
        if w == 0 or h == 0:
            return img
        if w >= h:
            new_w = self._size
            new_h = max(1, round(h * self._size / w))
        else:
            new_h = self._size
            new_w = max(1, round(w * self._size / h))
        return img.resize((new_w, new_h), Image.LANCZOS)

    @staticmethod
    def _to_buffer(img: Image.Image, fmt: str, **kwargs: int) -> io.BytesIO:
        buf = io.BytesIO()
        img.save(buf, format=fmt, **kwargs)
        buf.seek(0)
        return buf

    def _scale_filter(self) -> str:
        s = self._size
        return f"scale='if(gte(iw,ih),{s},-2)':'if(gte(iw,ih),-2,{s})'"

    def _video_filter(self) -> str:
        s = self._size
        return (
            f"{self._scale_filter()},"
            f"pad={s}:{s}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
            f"fps={self._video_fps},format=yuva420p"
        )

    def _ffmpeg_extract(self, data: bytes, *, middle: bool) -> Image.Image | None:
        src = self._write_temp(data, ".mp4")
        dst = src + ".png"
        try:
            scale = self._scale_filter()
            vf = f"select='eq(n\\,floor(t*25/2))',{scale}" if middle else scale
            self._run_ffmpeg(["-i", src, "-vf", vf, "-frames:v", "1", dst], timeout=30)
            return Image.open(dst).copy() if os.path.exists(dst) else None
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Frame extraction failed: %s", exc)
            return None
        finally:
            self._cleanup(src, dst)

    def _ffmpeg_video_sticker(self, data: bytes) -> VideoStickerResult:
        src = self._write_temp(data, ".mp4")
        outputs: list[str] = []
        last_reason = "WEBM video sticker could not be created"
        try:
            for crf in range(self._video_min_crf, self._video_max_crf + 1, self._video_crf_step):
                dst = f"{src}.crf{crf}.webm"
                outputs.append(dst)
                try:
                    self._run_ffmpeg([
                        "-i", src,
                        "-t", str(self._video_duration),
                        "-an",
                        "-vf", self._video_filter(),
                        "-c:v", "libvpx-vp9",
                        "-pix_fmt", "yuva420p",
                        "-b:v", "0",
                        "-crf", str(crf),
                        "-deadline", "good",
                        "-cpu-used", "4",
                        "-row-mt", "1",
                        "-auto-alt-ref", "0",
                        dst,
                    ], timeout=90)
                except (subprocess.TimeoutExpired, OSError) as exc:
                    last_reason = str(exc)
                    logger.warning("Video sticker WEBM conversion failed at CRF %d: %s", crf, exc)
                    continue

                valid, reason = self._validate_video_sticker(dst)
                if not valid:
                    last_reason = reason
                    continue

                buf = io.BytesIO(Path(dst).read_bytes())
                buf.seek(0)
                return VideoStickerResult(buf, size_bytes=os.path.getsize(dst))

            return VideoStickerResult(None, reason=last_reason)
        finally:
            self._cleanup(src, *outputs)

    def _validate_video_sticker(self, path: str) -> tuple[bool, str]:
        if not os.path.exists(path):
            return False, "WEBM output was not created"

        size = os.path.getsize(path)
        if size <= 0:
            return False, "WEBM output is empty"
        if size > self._video_max_bytes:
            logger.info(
                "Video sticker WEBM too large: %dKB > %dKB",
                size // 1024,
                self._video_max_bytes // 1024,
            )
            return False, "WEBM output is too large for Telegram video sticker limits"

        if not shutil.which("ffprobe"):
            return True, ""

        try:
            probe = subprocess.run([
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height",
                "-of", "csv=p=0",
                path,
            ], capture_output=True, text=True, timeout=15, check=False)
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.info("Video sticker ffprobe failed: %s", exc)
            return True, ""

        if probe.returncode != 0:
            logger.info("Video sticker ffprobe failed: %s", probe.stderr.strip())
            return True, ""

        fields = probe.stdout.strip().split(",")
        if len(fields) < 3:
            return False, "WEBM output could not be probed"
        codec, width_raw, height_raw = fields[:3]
        if codec != "vp9":
            return False, "WEBM output is not VP9"
        try:
            width = int(width_raw)
            height = int(height_raw)
        except ValueError:
            return False, "WEBM output dimensions could not be probed"
        if width > self._size or height > self._size:
            return False, "WEBM output is larger than the Telegram sticker canvas"

        return True, ""

    @staticmethod
    def _write_temp(data: bytes, suffix: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            return f.name

    @staticmethod
    def _run_ffmpeg(args: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(["ffmpeg", "-y", *args], capture_output=True, timeout=timeout, check=False)
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace").strip()
            raise OSError(stderr or "ffmpeg failed")
        return result

    @staticmethod
    def _cleanup(*paths: str) -> None:
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass
