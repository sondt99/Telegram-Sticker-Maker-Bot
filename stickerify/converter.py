from __future__ import annotations

import io
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from .config import Config

logger = logging.getLogger(__name__)


class StickerConverter:
    __slots__ = ("_size", "_quality", "_max_bytes", "_duration", "_fps", "_has_ffmpeg")

    def __init__(self, config: Config) -> None:
        self._size = config.sticker_size
        self._quality = config.webp_quality
        self._max_bytes = config.animated_max_bytes
        self._duration = config.animated_duration
        self._fps = config.animated_fps
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

    def to_animated_webp(self, data: bytes) -> io.BytesIO | None:
        if not self._has_ffmpeg:
            return None
        return self._ffmpeg_animate(data)

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
        ratio = self._size / max(w, h)
        return img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)

    @staticmethod
    def _to_buffer(img: Image.Image, fmt: str, **kwargs: int) -> io.BytesIO:
        buf = io.BytesIO()
        img.save(buf, format=fmt, **kwargs)
        buf.seek(0)
        return buf

    def _scale_filter(self) -> str:
        s = self._size
        return f"scale='if(gte(iw,ih),{s},-2)':'if(gte(iw,ih),-2,{s})'"

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

    def _ffmpeg_animate(self, data: bytes) -> io.BytesIO | None:
        src = self._write_temp(data, ".mp4")
        dst = src + ".webp"
        try:
            self._run_ffmpeg([
                "-i", src,
                "-vf", f"{self._scale_filter()},fps={self._fps}",
                "-t", str(self._duration),
                "-loop", "0",
                "-quality", "60",
                "-compression_level", "4",
                dst,
            ], timeout=60)
            if not os.path.exists(dst):
                return None
            size = os.path.getsize(dst)
            if size > self._max_bytes:
                logger.info("Animated WebP too large: %dKB > %dKB", size // 1024, self._max_bytes // 1024)
                return None
            buf = io.BytesIO(Path(dst).read_bytes())
            buf.seek(0)
            return buf
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Animated conversion failed: %s", exc)
            return None
        finally:
            self._cleanup(src, dst)

    @staticmethod
    def _write_temp(data: bytes, suffix: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            return f.name

    @staticmethod
    def _run_ffmpeg(args: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(["ffmpeg", "-y", *args], capture_output=True, timeout=timeout, check=False)

    @staticmethod
    def _cleanup(*paths: str) -> None:
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass
