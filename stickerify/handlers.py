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
_ALBUM_WAIT = 2.0


class Handlers:
    __slots__ = ("_conv",)

    def __init__(self, converter: StickerConverter) -> None:
        self._conv = converter

    # ── commands ──────────────────────────────────────────────

    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        ffmpeg = (
            "✅ FFmpeg available — GIF/video → WEBM VP9 supported"
            if self._conv.has_ffmpeg
            else "⚠️ FFmpeg not installed — static images only"
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
            "/rembg — toggle background removal\n\n"
            f"{ffmpeg}"
        )

    async def rembg(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        enabled = not context.user_data.get("rembg", False)
        context.user_data["rembg"] = enabled
        status = "ON ✅" if enabled else "OFF"
        await update.message.reply_text(
            f"🔄 Background removal: *{status}*\n\n"
            f"{'Send a photo to try it!' if enabled else 'Sending photos will keep the original background.'}",
            parse_mode="Markdown",
        )

    # ── media handlers ───────────────────────────────────────

    async def on_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        remove_bg = context.user_data.get("rembg", False)
        await self._ack(msg)

        if msg.media_group_id:
            await self._collect_album(msg, context, remove_bg)
            return

        data = await (await msg.photo[-1].get_file()).download_as_bytearray()
        img = Image.open(io.BytesIO(data))

        if remove_bg:
            await msg.reply_text("⏳ Removing background…")

        png, webp = self._conv.convert(img, remove_bg=remove_bg)
        suffix = " (bg removed)" if remove_bg else ""
        await self._send_pair(msg, png, webp, f"PNG — {img.width}x{img.height} → 512px{suffix}")

    async def on_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        doc = msg.document
        mime = doc.mime_type or ""
        fname = (doc.file_name or "").lower()
        remove_bg = context.user_data.get("rembg", False)
        await self._ack(msg)

        if mime.startswith("image/") and "gif" not in mime:
            data = await (await doc.get_file()).download_as_bytearray()
            img = Image.open(io.BytesIO(data))

            if remove_bg:
                await msg.reply_text("⏳ Removing background…")

            png, webp = self._conv.convert(img, remove_bg=remove_bg)
            suffix = " (bg removed)" if remove_bg else ""
            await self._send_pair(msg, png, webp, f"PNG 512px{suffix}")
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
        data = bytes(await (await sticker.get_file()).download_as_bytearray())
        remove_bg = context.user_data.get("rembg", False)
        await self._ack(msg)

        if sticker.is_animated and not sticker.is_video:
            await msg.reply_text(
                "⚠️ TGS animated stickers are not supported yet. "
                "Send a static/video sticker, GIF, or short video instead."
            )
            return

        if sticker.is_video:
            if not self._conv.has_ffmpeg:
                await msg.reply_text("⚠️ Video stickers require FFmpeg.")
                return
            img = self._conv.extract_frame_original(data)
            if not img:
                await msg.reply_text("❌ Failed to extract frame from this video sticker.")
                return
            await msg.reply_document(
                InputFile(io.BytesIO(data), "original_video_sticker.webm"),
                caption="🎬 Original WEBM — video sticker pack file",
            )
        else:
            img = Image.open(io.BytesIO(data))

        if remove_bg:
            await msg.reply_text("⏳ Removing background…")
            img = self._conv.remove_background(img)

        original = self._conv.to_png(img)
        await msg.reply_document(
            InputFile(original, "original.png"),
            caption=f"🖼 Original quality — {img.width}x{img.height}px",
        )

        png, webp = self._conv.convert(img)
        suffix = " (bg removed)" if remove_bg else ""
        await self._send_pair(msg, png, webp, f"PNG 512px{suffix}")

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

        data = bytes(await (await msg.photo[-1].get_file()).download_as_bytearray())

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

        tag = " + bg removal" if remove_bg else ""
        await context.bot.send_message(chat_id, f"⏳ Processing {count} photos{tag}…")

        for i, photo_data in enumerate(photos, 1):
            img = Image.open(io.BytesIO(photo_data))
            png, webp = self._conv.convert(img, remove_bg=remove_bg)
            label = f"[{i}/{count}]"
            await context.bot.send_document(
                chat_id, InputFile(png, f"sticker_{i}.png"), caption=f"📐 {label} PNG 512px"
            )
            await context.bot.send_document(
                chat_id, InputFile(webp, f"sticker_{i}.webp"), caption=f"📐 {label} WebP"
            )

        await context.bot.send_message(chat_id, f"✅ Done! {count} photos converted.")

    # ── helpers ───────────────────────────────────────────────

    async def _process_video(self, msg: Message, media: object) -> None:
        if not self._conv.has_ffmpeg:
            await msg.reply_text("⚠️ FFmpeg is not installed.")
            return

        await msg.reply_text("⏳ Processing…")
        data = bytes(await (await media.get_file()).download_as_bytearray())  # type: ignore[union-attr]

        img = self._conv.extract_frame(data)
        if not img:
            await msg.reply_text("❌ Failed to extract frame.")
            return

        png, webp = self._conv.convert(img)
        await msg.reply_document(
            InputFile(png, "sticker_frame.png"),
            caption="📐 PNG first frame — for static sticker packs",
        )
        await msg.reply_document(
            InputFile(webp, "sticker_frame.webp"),
            caption="📐 WebP first frame — for static sticker packs",
        )

        video = self._conv.to_video_sticker(data)
        if video.ok and video.buffer:
            size = f" ({video.size_bytes // 1024}KB)" if video.size_bytes else ""
            await msg.reply_document(
                InputFile(video.buffer, "video_sticker.webm"),
                caption=f"🎬 WEBM VP9{size} — for Telegram video sticker packs only",
            )
            await msg.reply_text("ℹ️ Static PNG/WebP and video WEBM must be added to separate sticker packs.")
            return

        message = (
            "⚠️ Could not create a WEBM video sticker within Telegram limits.\n"
            "Use the static PNG/WebP above, or try a shorter/simpler GIF/video."
        )
        if video.reason:
            message += f"\nReason: {video.reason}"
        await msg.reply_text(message)

    @staticmethod
    async def _send_pair(msg: Message, png: io.BytesIO, webp: io.BytesIO, caption: str) -> None:
        await msg.reply_document(InputFile(png, "sticker.png"), caption=f"📐 {caption}")
        await msg.reply_document(InputFile(webp, "sticker.webp"), caption="📐 WebP — ready for sticker!")

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
