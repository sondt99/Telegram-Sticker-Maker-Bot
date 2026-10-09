from __future__ import annotations

import asyncio
import io
from typing import Any

from PIL import Image

from stickerify.config import Config
from stickerify.converter import StaticStickerResult, StickerConverter, VideoStickerResult
from stickerify.handlers import Handlers, on_error


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _png_bytes(size: tuple[int, int] = (40, 20), color: str = "red") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class FakeFile:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def download_as_bytearray(self) -> bytearray:
        return bytearray(self._data)


class FakeMedia:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.get_file_calls = 0

    async def get_file(self) -> FakeFile:
        self.get_file_calls += 1
        return FakeFile(self._data)


class FakeSticker(FakeMedia):
    def __init__(self, data: bytes, *, is_animated: bool = False, is_video: bool = False) -> None:
        super().__init__(data)
        self.is_animated = is_animated
        self.is_video = is_video


class FakeDocument(FakeMedia):
    def __init__(self, data: bytes, *, mime_type: str = "", file_name: str = "") -> None:
        super().__init__(data)
        self.mime_type = mime_type
        self.file_name = file_name


class FakeMessage:
    def __init__(
        self,
        *,
        photo: list[FakeMedia] | None = None,
        document: FakeDocument | None = None,
        sticker: FakeSticker | None = None,
        animation: FakeMedia | None = None,
        video: FakeMedia | None = None,
        media_group_id: str | None = None,
        chat_id: int = 99,
    ) -> None:
        self.photo = photo or []
        self.document = document
        self.sticker = sticker
        self.animation = animation
        self.video = video
        self.media_group_id = media_group_id
        self.chat_id = chat_id
        self.texts: list[str] = []
        self.documents: list[tuple[str, str]] = []
        self.reactions: list[str] = []

    async def reply_text(self, text: str, **_: Any) -> None:
        self.texts.append(text)

    async def reply_document(self, document: Any, caption: str = "", **_: Any) -> None:
        self.documents.append((document.filename, caption))

    async def set_reaction(self, reaction: str) -> None:
        self.reactions.append(reaction)

    @property
    def all_text(self) -> str:
        return "\n".join(self.texts)

    @property
    def doc_names(self) -> list[str]:
        return [name for name, _ in self.documents]


class FakeBot:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.documents: list[tuple[int, str, str]] = []

    async def send_message(self, chat_id: int, text: str, **_: Any) -> None:
        self.texts.append(text)

    async def send_document(self, chat_id: int, document: Any, caption: str = "", **_: Any) -> None:
        self.documents.append((chat_id, document.filename, caption))

    @property
    def all_text(self) -> str:
        return "\n".join(self.texts)


class FakeJob:
    def __init__(self, data: str) -> None:
        self.data = data


class FakeJobQueue:
    def __init__(self) -> None:
        self.scheduled: list[tuple[Any, float, str]] = []

    def run_once(self, callback: Any, when: float, *, data: str, name: str) -> None:
        self.scheduled.append((callback, when, data))


class FakeContext:
    def __init__(self, *, job_queue: FakeJobQueue | None = None, job: FakeJob | None = None) -> None:
        self.user_data: dict[str, Any] = {}
        self.bot_data: dict[str, Any] = {}
        self.job_queue = job_queue
        self.job = job
        self.bot = FakeBot()
        self.error: BaseException | None = None


class FakeUpdate:
    def __init__(self, message: FakeMessage) -> None:
        self.message = message


def _handlers(**config_kwargs: Any) -> Handlers:
    return Handlers(StickerConverter(Config(bot_token="token", **config_kwargs)))


def _no_rembg(monkeypatch) -> None:
    """rembg is an optional heavy dependency; keep the image untouched instead."""
    monkeypatch.setattr(StickerConverter, "remove_background", staticmethod(lambda img: img))


# ── commands ──────────────────────────────────────────────


def test_start_reports_video_tooling_as_ready() -> None:
    h = _handlers(ffmpeg_available=True, ffprobe_available=True)
    msg = FakeMessage()

    _run(h.start(FakeUpdate(msg), FakeContext()))

    assert "FFmpeg + FFprobe available" in msg.all_text


def test_start_reports_video_tooling_as_incomplete_without_ffprobe() -> None:
    h = _handlers(ffmpeg_available=True, ffprobe_available=False)
    msg = FakeMessage()

    _run(h.start(FakeUpdate(msg), FakeContext()))

    assert "FFmpeg/FFprobe incomplete" in msg.all_text


def test_rembg_toggles_state_both_ways() -> None:
    h = _handlers()
    context = FakeContext()

    msg_on = FakeMessage()
    _run(h.rembg(FakeUpdate(msg_on), context))
    assert context.user_data["rembg"] is True
    assert "ON" in msg_on.all_text

    msg_off = FakeMessage()
    _run(h.rembg(FakeUpdate(msg_off), context))
    assert context.user_data["rembg"] is False
    assert "OFF" in msg_off.all_text
    assert "keep the original background" in msg_off.all_text


# ── photos and documents ─────────────────────────────────


def test_on_photo_acks_and_sends_png_and_webp() -> None:
    h = _handlers()
    msg = FakeMessage(photo=[FakeMedia(_png_bytes())])

    _run(h.on_photo(FakeUpdate(msg), FakeContext()))

    assert msg.reactions == ["👀"]
    assert msg.doc_names == ["sticker.png", "sticker.webp"]


def test_on_photo_announces_background_removal(monkeypatch) -> None:
    _no_rembg(monkeypatch)
    h = _handlers()
    msg = FakeMessage(photo=[FakeMedia(_png_bytes())])
    context = FakeContext()
    context.user_data["rembg"] = True

    _run(h.on_photo(FakeUpdate(msg), context))

    assert "Removing background" in msg.all_text
    assert any("bg removed" in caption for _, caption in msg.documents)


def test_on_photo_reports_unreadable_image() -> None:
    h = _handlers()
    msg = FakeMessage(photo=[FakeMedia(b"not an image")])

    _run(h.on_photo(FakeUpdate(msg), FakeContext()))

    assert "couldn't read this image" in msg.all_text
    assert msg.documents == []


def test_on_photo_reports_download_failure() -> None:
    class BrokenMedia(FakeMedia):
        async def get_file(self) -> FakeFile:
            raise RuntimeError("network down")

    h = _handlers()
    msg = FakeMessage(photo=[BrokenMedia(b"")])

    _run(h.on_photo(FakeUpdate(msg), FakeContext()))

    assert "Failed to download" in msg.all_text
    assert msg.documents == []


def test_on_document_converts_image_file() -> None:
    h = _handlers()
    doc = FakeDocument(_png_bytes(), mime_type="image/png", file_name="pic.png")
    msg = FakeMessage(document=doc)

    _run(h.on_document(FakeUpdate(msg), FakeContext()))

    assert msg.doc_names == ["sticker.png", "sticker.webp"]


def test_on_document_rejects_unknown_type() -> None:
    h = _handlers()
    doc = FakeDocument(b"data", mime_type="application/zip", file_name="archive.zip")
    msg = FakeMessage(document=doc)

    _run(h.on_document(FakeUpdate(msg), FakeContext()))

    assert "Unrecognized file type" in msg.all_text
    assert msg.documents == []


# ── stickers ──────────────────────────────────────────────


def test_on_sticker_rejects_tgs_without_downloading() -> None:
    h = _handlers()
    sticker = FakeSticker(b"tgs", is_animated=True, is_video=False)
    msg = FakeMessage(sticker=sticker)

    _run(h.on_sticker(FakeUpdate(msg), FakeContext()))

    assert "TGS animated stickers are not supported" in msg.all_text
    assert sticker.get_file_calls == 0
    assert msg.documents == []


def test_on_sticker_video_requires_ffmpeg_before_downloading() -> None:
    h = _handlers(ffmpeg_available=False)
    sticker = FakeSticker(b"webm", is_animated=True, is_video=True)
    msg = FakeMessage(sticker=sticker)

    _run(h.on_sticker(FakeUpdate(msg), FakeContext()))

    assert "Video stickers require FFmpeg" in msg.all_text
    assert sticker.get_file_calls == 0


def test_on_sticker_static_sends_original_then_converted_pair() -> None:
    h = _handlers()
    msg = FakeMessage(sticker=FakeSticker(_png_bytes((60, 30))))

    _run(h.on_sticker(FakeUpdate(msg), FakeContext()))

    assert msg.doc_names == ["original.png", "sticker.png", "sticker.webp"]
    assert "60x30px" in msg.documents[0][1]


def test_on_sticker_video_sends_webm_then_frame(monkeypatch) -> None:
    h = _handlers(ffmpeg_available=True, ffprobe_available=True)
    monkeypatch.setattr(
        StickerConverter, "extract_frame_original", lambda self, data: Image.new("RGB", (70, 70), "blue")
    )
    msg = FakeMessage(sticker=FakeSticker(b"webm bytes", is_animated=True, is_video=True))

    _run(h.on_sticker(FakeUpdate(msg), FakeContext()))

    assert msg.doc_names == [
        "original_video_sticker.webm",
        "original_frame.png",
        "sticker.png",
        "sticker.webp",
    ]


def test_on_sticker_video_reports_failed_frame_extraction(monkeypatch) -> None:
    h = _handlers(ffmpeg_available=True, ffprobe_available=True)
    monkeypatch.setattr(StickerConverter, "extract_frame_original", lambda self, data: None)
    msg = FakeMessage(sticker=FakeSticker(b"webm bytes", is_animated=True, is_video=True))

    _run(h.on_sticker(FakeUpdate(msg), FakeContext()))

    assert "Failed to extract frame" in msg.all_text
    assert msg.documents == []


# ── albums ────────────────────────────────────────────────


def test_collect_album_schedules_single_job_per_group() -> None:
    h = _handlers()
    queue = FakeJobQueue()
    context = FakeContext(job_queue=queue)

    for _ in range(3):
        msg = FakeMessage(photo=[FakeMedia(_png_bytes())], media_group_id="group-1")
        _run(h.on_photo(FakeUpdate(msg), context))

    assert len(queue.scheduled) == 1
    key = queue.scheduled[0][2]
    assert len(context.bot_data["albums"][key]["photos"]) == 3


def test_collect_album_falls_back_when_job_queue_missing() -> None:
    h = _handlers()
    context = FakeContext(job_queue=None)
    msg = FakeMessage(photo=[FakeMedia(_png_bytes())], media_group_id="group-1")

    _run(h.on_photo(FakeUpdate(msg), context))

    assert "Album batching is unavailable" in msg.all_text
    assert msg.doc_names == ["sticker.png", "sticker.webp"]


def test_process_album_converts_every_photo() -> None:
    h = _handlers()
    key = "album_99_group-1"
    context = FakeContext(job=FakeJob(key))
    context.bot_data["albums"] = {
        key: {"photos": [_png_bytes(), _png_bytes()], "chat_id": 99, "remove_bg": False}
    }

    _run(h._process_album(context))

    assert len(context.bot.documents) == 4
    assert "2 photos converted" in context.bot.all_text
    assert context.bot_data["albums"] == {}


def test_process_album_reports_per_item_failures() -> None:
    h = _handlers()
    key = "album_99_group-1"
    context = FakeContext(job=FakeJob(key))
    context.bot_data["albums"] = {
        key: {"photos": [_png_bytes(), b"corrupt"], "chat_id": 99, "remove_bg": False}
    }

    _run(h._process_album(context))

    assert len(context.bot.documents) == 2
    assert "Converted 1/2 photos. Failed 1." in context.bot.all_text


def test_process_album_ignores_unknown_job_key() -> None:
    h = _handlers()
    context = FakeContext(job=FakeJob("missing"))

    _run(h._process_album(context))

    assert context.bot.texts == []


# ── video ─────────────────────────────────────────────────


def test_process_video_sends_frames_and_webm(monkeypatch) -> None:
    h = _handlers(ffmpeg_available=True, ffprobe_available=True)
    monkeypatch.setattr(StickerConverter, "extract_frame", lambda self, data: Image.new("RGB", (80, 40), "green"))
    monkeypatch.setattr(
        StickerConverter,
        "to_video_sticker",
        lambda self, data: VideoStickerResult(io.BytesIO(b"webm"), size_bytes=2048),
    )
    msg = FakeMessage(animation=FakeMedia(b"gif bytes"))

    _run(h.on_animation(FakeUpdate(msg), FakeContext()))

    assert msg.doc_names == ["sticker_frame.png", "sticker_frame.webp", "video_sticker.webm"]
    assert "2KB" in msg.documents[-1][1]
    assert "separate sticker packs" in msg.all_text


def test_process_video_reports_reason_when_webm_fails(monkeypatch) -> None:
    h = _handlers(ffmpeg_available=True, ffprobe_available=False)
    monkeypatch.setattr(StickerConverter, "extract_frame", lambda self, data: Image.new("RGB", (80, 40), "green"))
    msg = FakeMessage(video=FakeMedia(b"video bytes"))

    _run(h.on_video(FakeUpdate(msg), FakeContext()))

    assert msg.doc_names == ["sticker_frame.png", "sticker_frame.webp"]
    assert "FFprobe is required to verify video stickers" in msg.all_text


def test_process_video_reports_failed_frame_extraction(monkeypatch) -> None:
    h = _handlers(ffmpeg_available=True, ffprobe_available=True)
    monkeypatch.setattr(StickerConverter, "extract_frame", lambda self, data: None)
    msg = FakeMessage(video=FakeMedia(b"video bytes"))

    _run(h.on_video(FakeUpdate(msg), FakeContext()))

    assert "Failed to extract frame" in msg.all_text
    assert msg.documents == []


def test_on_video_requires_ffmpeg() -> None:
    h = _handlers(ffmpeg_available=False)
    msg = FakeMessage(video=FakeMedia(b"video bytes"))

    _run(h.on_video(FakeUpdate(msg), FakeContext()))

    assert "FFmpeg is not installed" in msg.all_text


# ── delivery of static results ───────────────────────────


def test_send_static_result_surfaces_warnings() -> None:
    h = _handlers()
    msg = FakeMessage()
    result = StaticStickerResult(None, io.BytesIO(b"webp"), warnings=("PNG output is larger",))

    sent = _run(h._send_static_result(msg, result, "caption"))

    assert sent is True
    assert msg.doc_names == ["sticker.webp"]
    assert "PNG output is larger" in msg.all_text


def test_send_static_result_reports_when_nothing_fits() -> None:
    h = _handlers()
    msg = FakeMessage()
    result = StaticStickerResult(None, None, warnings=())

    sent = _run(h._send_static_result(msg, result, "caption"))

    assert sent is False
    assert msg.documents == []
    assert "exceeded Telegram limits" in msg.all_text


# ── unknown input and error handler ──────────────────────


def test_on_unknown_points_at_start() -> None:
    h = _handlers()
    msg = FakeMessage()

    _run(h.on_unknown(FakeUpdate(msg), FakeContext()))

    assert "/start" in msg.all_text


def test_on_error_survives_a_non_update_object() -> None:
    context = FakeContext()
    context.error = RuntimeError("boom")

    _run(on_error(object(), context))
