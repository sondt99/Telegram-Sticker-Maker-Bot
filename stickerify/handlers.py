from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

from PIL import Image
from telegram import InputFile, Update
from telegram.ext import ContextTypes

from .converter import StickerConverter

if TYPE_CHECKING:
    from telegram import Message

logger = logging.getLogger(__name__)

_VIDEO_EXTENSIONS = (".gif", ".mp4", ".webm", ".mov")


class Handlers:
    __slots__ = ("_conv",)

    def __init__(self, converter: StickerConverter) -> None:
        self._conv = converter

    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ffmpeg = (
            "✅ FFmpeg available — video/GIF supported"
            if self._conv.has_ffmpeg
            else "⚠️ FFmpeg not installed — static images only"
        )
        await update.message.reply_text(
            "🎨 *Sticker Maker Bot*\n\n"
            "Send me:\n"
            "• 🖼 Photo\n"
            "• 📎 Image file (jpg, png, bmp, tiff…)\n"
            "• 🎬 GIF / Short video\n"
            "• 😀 Sticker\n\n"
            f"I'll send back *PNG + WebP* at 512px, ready for stickers!\n\n{ffmpeg}",
            parse_mode="Markdown",
        )

    async def on_photo(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        photo = msg.photo[-1]
        data = await (await photo.get_file()).download_as_bytearray()

        img = Image.open(io.BytesIO(data))
        png, webp = self._conv.convert(img)
        await self._send_pair(msg, png, webp, f"PNG — {img.width}x{img.height} → 512px")

    async def on_document(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        doc = msg.document
        mime = doc.mime_type or ""
        fname = (doc.file_name or "").lower()

        if mime.startswith("image/") and "gif" not in mime:
            data = await (await doc.get_file()).download_as_bytearray()
            img = Image.open(io.BytesIO(data))
            png, webp = self._conv.convert(img)
            await self._send_pair(msg, png, webp, "PNG 512px")
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
        if not self._conv.has_ffmpeg:
            await update.message.reply_text("⚠️ FFmpeg is not installed — cannot process GIFs.")
            return
        await self._process_video(update.message, update.message.animation)

    async def on_video(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._conv.has_ffmpeg:
            await update.message.reply_text("⚠️ FFmpeg is not installed — cannot process videos.")
            return
        await self._process_video(update.message, update.message.video)

    async def on_sticker(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        sticker = msg.sticker
        data = bytes(await (await sticker.get_file()).download_as_bytearray())

        if sticker.is_animated or sticker.is_video:
            if not self._conv.has_ffmpeg:
                await msg.reply_text("⚠️ Animated stickers require FFmpeg.")
                return
            img = self._conv.extract_frame(data)
            if not img:
                await msg.reply_text("❌ Failed to extract frame from animated sticker.")
                return
            png, webp = self._conv.convert(img)
            await self._send_pair(msg, png, webp, "PNG (frame from animated sticker)")
            return

        img = Image.open(io.BytesIO(data))
        png, webp = self._conv.convert(img)
        await self._send_pair(msg, png, webp, "PNG 512px")

    async def on_unknown(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "💡 Send a photo, GIF, video, or sticker to convert!\nType /start for instructions."
        )

    async def _process_video(self, msg: Message, media: object) -> None:
        if not self._conv.has_ffmpeg:
            await msg.reply_text("⚠️ FFmpeg is not installed.")
            return

        await msg.reply_text("⏳ Processing…")
        data = bytes(await (await media.get_file()).download_as_bytearray())  # type: ignore[union-attr]

        animated = self._conv.to_animated_webp(data)
        img = self._conv.extract_frame(data)
        if not img:
            await msg.reply_text("❌ Failed to extract frame.")
            return

        png, webp = self._conv.convert(img)
        await msg.reply_document(InputFile(png, "sticker_frame.png"), caption="📐 PNG (first frame)")

        if animated:
            await msg.reply_document(InputFile(animated, "sticker_animated.webp"), caption="🎬 Animated WebP — animated sticker!")
        else:
            await msg.reply_document(InputFile(webp, "sticker.webp"), caption="📐 Static WebP")

    @staticmethod
    async def _send_pair(msg: Message, png: io.BytesIO, webp: io.BytesIO, caption: str) -> None:
        await msg.reply_document(InputFile(png, "sticker.png"), caption=f"📐 {caption}")
        await msg.reply_document(InputFile(webp, "sticker.webp"), caption="📐 WebP — ready for sticker!")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text("❌ Something went wrong. Please try again.")
        except Exception:
            pass
