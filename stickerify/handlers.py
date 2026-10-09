from __future__ import annotations

import asyncio
import io
import logging
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from PIL import Image, UnidentifiedImageError
from telegram import InputFile, Update
from telegram.ext import ContextTypes

from .converter import StaticStickerResult, StickerConverter

if TYPE_CHECKING:
    from telegram import Message

logger = logging.getLogger(__name__)

_VIDEO_EXTENSIONS = (".gif", ".mp4", ".webm", ".mov")
_ALBUM_WAIT = 2.0
_UNREADABLE_IMAGE = "❌ I couldn't read this image. Try a PNG, JPG, or WebP file."
_CONVERSION_FAILED = "❌ Failed to convert this image. Please try another file."
_REMOVING_BACKGROUND = "⏳ Removing background…"
_T = TypeVar("_T")


class Handlers:
    __slots__ = ("_conv",)

    def __init__(self, converter: StickerConverter) -> None:
        self._conv = converter

    # ── commands ──────────────────────────────────────────────

    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        video_status = (
            "✅ FFmpeg + FFprobe available — GIF/video → verified WEBM VP9 supported"
            if self._conv.has_video_tools
            else "⚠️ FFmpeg/FFprobe incomplete — static images only or frame extraction only"
        )
        await update.message.reply_text(
            "🎨 Sticker Maker Bot\n\n"
            "Send me:\n"
            "• 🖼 Photo or album → static PNG + WebP\n"
            "• 📎 Image file (jpg, png, bmp, tiff…)\n"
            "• 🎬 GIF / Short video → static frame + WEBM VP9 video sticker\n"
            "• 😀 Sticker → original HD image + sticker-ready files\n\n"
            "Telegram packs are type-locked: static PNG/WebP and video WEBM need separate packs.\n\n"
            "Commands:\n"
            "/rembg — toggle background removal for photos, image files, static stickers, and photo albums\n\n"
            f"{video_status}"
        )

    async def rembg(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        enabled = not context.user_data.get("rembg", False)
        context.user_data["rembg"] = enabled
        status = "ON ✅" if enabled else "OFF"
        detail = (
            "Photos, image files, static stickers, and photo albums will use background removal. "
            "GIF/video WEBM output is unchanged."
            if enabled
            else "Photos, image files, static stickers, and albums will keep the original background."
        )
        await update.message.reply_text(f"🔄 Background removal: {status}\n\n{detail}")

    # ── media handlers ───────────────────────────────────────

    async def on_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        remove_bg = context.user_data.get("rembg", False)
        await self._ack(msg)

        if msg.media_group_id:
            await self._collect_album(msg, context, remove_bg)
            return

        await self._process_image_media(msg, msg.photo[-1], remove_bg, "PNG — photo → 512px")

    async def on_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        doc = msg.document
        mime = doc.mime_type or ""
        fname = (doc.file_name or "").lower()
        remove_bg = context.user_data.get("rembg", False)
        await self._ack(msg)

        if mime.startswith("image/") and "gif" not in mime:
            await self._process_image_media(msg, doc, remove_bg, "PNG — image file → 512px")
            return

        is_video = (
            mime.startswith("video/")
            or "gif" in mime
            or any(fname.endswith(ext) for ext in _VIDEO_EXTENSIONS)
        )
        if is_video:
            await self._process_video(msg, doc)
            return

        await msg.reply_text("🤔 Unrecognized file type.\nSend an image, GIF, or short video!")

    async def on_animation(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        await self._ack(msg)
        if not self._conv.has_ffmpeg:
            await msg.reply_text("⚠️ FFmpeg is not installed — cannot process GIFs.")
            return
        await self._process_video(msg, msg.animation)

    async def on_video(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        await self._ack(msg)
        if not self._conv.has_ffmpeg:
            await msg.reply_text("⚠️ FFmpeg is not installed — cannot process videos.")
            return
        await self._process_video(msg, msg.video)

    async def on_sticker(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        sticker = msg.sticker
        remove_bg = context.user_data.get("rembg", False)
        await self._ack(msg)

        if sticker.is_animated and not sticker.is_video:
            await msg.reply_text(
                "⚠️ TGS animated stickers are not supported yet. "
                "Telegram animated stickers use Lottie/TGS, not GIF/WebP conversion."
            )
            return

        if sticker.is_video and not self._conv.has_ffmpeg:
            await msg.reply_text("⚠️ Video stickers require FFmpeg.")
            return

        data = await self._download_media_bytes(sticker)

        if sticker.is_video:
            img = await self._run_blocking(self._conv.extract_frame_original, data)
            if not img:
                await msg.reply_text("❌ Failed to extract frame from this video sticker.")
                return
            await msg.reply_document(
                InputFile(io.BytesIO(data), "original_video_sticker.webm"),
                caption="🎬 Original WEBM — video sticker pack file",
            )
            original_name, original_label = "original_frame.png", "🖼 Original video frame"
        else:
            img = await self._safe_open_image(msg, data)
            if img is None:
                return
            original_name, original_label = "original.png", "🖼 Original quality"

        original = await self._run_blocking(self._conv.to_png, img)
        await msg.reply_document(
            InputFile(original, original_name),
            caption=f"{original_label} — {img.width}x{img.height}px",
        )

        result = await self._convert_image(msg, img, remove_bg)
        if result is None:
            return
        suffix = " (bg removed)" if remove_bg else ""
        await self._send_static_result(msg, result, f"PNG 512px{suffix}")

    async def on_unknown(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "💡 Send a photo, GIF, video, or sticker to convert!\nType /start for instructions."
        )

    # ── album (batch) ────────────────────────────────────────

    async def _collect_album(
        self, msg: Message, context: ContextTypes.DEFAULT_TYPE, remove_bg: bool
    ) -> None:
        group_id = msg.media_group_id
        key = f"album_{msg.chat_id}_{group_id}"
        data = await self._download_media_bytes(msg.photo[-1])

        if context.job_queue is None:
            await msg.reply_text("⚠️ Album batching is unavailable; processing this photo individually.")
            img = await self._safe_open_image(msg, data)
            if img is None:
                return
            result = await self._convert_image(msg, img, remove_bg)
            if result is None:
                return
            await self._send_static_result(msg, result, "PNG — album photo → 512px")
            return

        albums = context.bot_data.setdefault("albums", {})
        if key not in albums:
            albums[key] = {"photos": [], "chat_id": msg.chat_id, "remove_bg": remove_bg}
            context.job_queue.run_once(self._process_album, _ALBUM_WAIT, data=key, name=key)

        albums[key]["photos"].append(data)

    async def _process_album(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        key = context.job.data
        albums = context.bot_data.get("albums", {})
        album = albums.pop(key, None)
        if not album:
            return

        chat_id = album["chat_id"]
        photos = album["photos"]
        remove_bg = album["remove_bg"]
        count = len(photos)
        converted = 0
        failed = 0

        tag = " + bg removal" if remove_bg else ""
        await context.bot.send_message(chat_id, f"⏳ Processing {count} photos{tag}…")

        for i, photo_data in enumerate(photos, 1):
            label = f"[{i}/{count}]"
            try:
                img = await self._open_image_from_bytes(photo_data)
                result = await self._convert_static(img, remove_bg=remove_bg)
                sent = await self._send_static_result_to_chat(context, chat_id, result, i, label)
                if sent:
                    converted += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
                logger.exception("Album item %s failed", label)
                await context.bot.send_message(chat_id, f"❌ {label} Failed to convert this photo.")

        if failed:
            await context.bot.send_message(chat_id, f"✅ Converted {converted}/{count} photos. Failed {failed}.")
        else:
            await context.bot.send_message(chat_id, f"✅ Done! {count} photos converted.")

    # ── helpers ───────────────────────────────────────────────

    async def _process_video(self, msg: Message, media: object) -> None:
        if not self._conv.has_ffmpeg:
            await msg.reply_text("⚠️ FFmpeg is not installed.")
            return

        await msg.reply_text("⏳ Processing…")
        data = await self._download_media_bytes(media)

        img = await self._run_blocking(self._conv.extract_frame, data)
        if not img:
            await msg.reply_text("❌ Failed to extract frame.")
            return

        result = await self._convert_static(img)
        await self._send_static_result(
            msg,
            result,
            "PNG first frame — for static sticker packs",
            png_name="sticker_frame.png",
            webp_name="sticker_frame.webp",
            webp_caption="WebP first frame — for static sticker packs",
        )

        video = await self._run_blocking(self._conv.to_video_sticker, data)
        if video.ok and video.buffer:
            size = f" ({video.size_bytes // 1024}KB)" if video.size_bytes else ""
            await msg.reply_document(
                InputFile(video.buffer, "video_sticker.webm"),
                caption=f"🎬 WEBM VP9{size} — for Telegram video sticker packs only",
            )
            await msg.reply_text("ℹ️ Static PNG/WebP and video WEBM must be added to separate sticker packs.")
            return

        message = (
            "⚠️ Could not create a Telegram-ready WEBM video sticker.\n"
            "Try a shorter, smaller, or simpler GIF/video. Static PNG/WebP frames are attached above."
        )
        if video.reason:
            message += f"\nReason: {video.reason}"
        await msg.reply_text(message)

    async def _process_image_media(
        self, msg: Message, media: object, remove_bg: bool, caption: str
    ) -> None:
        try:
            data = await self._download_media_bytes(media)
        except Exception:
            logger.exception("Media download failed")
            await msg.reply_text("❌ Failed to download this file. Please try again.")
            return

        img = await self._safe_open_image(msg, data)
        if img is None:
            return

        result = await self._convert_image(msg, img, remove_bg)
        if result is None:
            return

        suffix = " (bg removed)" if remove_bg else ""
        await self._send_static_result(msg, result, f"{caption}{suffix}")

    async def _safe_open_image(self, msg: Message, data: bytes) -> Image.Image | None:
        try:
            return await self._open_image_from_bytes(data)
        except (UnidentifiedImageError, OSError):
            logger.exception("Image open failed")
            await msg.reply_text(_UNREADABLE_IMAGE)
            return None

    async def _convert_image(
        self, msg: Message, img: Image.Image, remove_bg: bool
    ) -> StaticStickerResult | None:
        if remove_bg:
            await msg.reply_text(_REMOVING_BACKGROUND)
        try:
            return await self._convert_static(img, remove_bg=remove_bg)
        except Exception:
            logger.exception("Image conversion failed")
            await msg.reply_text(_CONVERSION_FAILED)
            return None

    async def _download_media_bytes(self, media: object) -> bytes:
        file = await media.get_file()  # type: ignore[union-attr]
        return bytes(await file.download_as_bytearray())

    async def _open_image_from_bytes(self, data: bytes) -> Image.Image:
        def open_copy() -> Image.Image:
            with Image.open(io.BytesIO(data)) as img:
                img.load()
                return img.copy()

        return await self._run_blocking(open_copy)

    async def _convert_static(self, img: Image.Image, *, remove_bg: bool = False) -> StaticStickerResult:
        return await self._run_blocking(self._conv.convert_static, img, remove_bg=remove_bg)

    async def _send_static_result(
        self,
        msg: Message,
        result: StaticStickerResult,
        png_caption: str,
        *,
        png_name: str = "sticker.png",
        webp_name: str = "sticker.webp",
        webp_caption: str = "WebP — ready for static sticker packs",
    ) -> bool:
        sent = 0
        if result.png:
            await msg.reply_document(InputFile(result.png, png_name), caption=f"📐 {png_caption}")
            sent += 1
        if result.webp:
            await msg.reply_document(InputFile(result.webp, webp_name), caption=f"📐 {webp_caption}")
            sent += 1
        if result.warnings:
            await msg.reply_text("⚠️ " + "\n".join(result.warnings))
        if not sent:
            await msg.reply_text("❌ Static sticker output exceeded Telegram limits.")
        return sent > 0

    async def _send_static_result_to_chat(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        result: StaticStickerResult,
        index: int,
        label: str,
    ) -> bool:
        sent = 0
        if result.png:
            await context.bot.send_document(
                chat_id, InputFile(result.png, f"sticker_{index}.png"), caption=f"📐 {label} PNG 512px"
            )
            sent += 1
        if result.webp:
            await context.bot.send_document(
                chat_id, InputFile(result.webp, f"sticker_{index}.webp"), caption=f"📐 {label} WebP"
            )
            sent += 1
        if result.warnings:
            await context.bot.send_message(chat_id, f"⚠️ {label} " + "\n".join(result.warnings))
        return sent > 0

    async def _run_blocking(self, func: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
        return await asyncio.to_thread(func, *args, **kwargs)

    @staticmethod
    async def _ack(msg: Message) -> None:
        try:
            await msg.set_reaction("👀")
        except Exception:
            pass


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text("❌ Something went wrong. Please try again.")
        except Exception:
            pass
