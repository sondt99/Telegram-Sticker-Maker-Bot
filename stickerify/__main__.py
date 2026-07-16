"""Entry point: python -m stickerify."""

from __future__ import annotations

import logging

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .config import Config
from .converter import StickerConverter
from .handlers import Handlers, on_error

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("stickerify")


def main() -> None:
    config = Config.from_env()
    converter = StickerConverter(config)
    h = Handlers(converter)

    logger.info("FFmpeg: %s", "available" if converter.has_ffmpeg else "not found")

    app = Application.builder().token(config.bot_token).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", h.start))
    app.add_handler(CommandHandler("rembg", h.rembg))
    app.add_handler(MessageHandler(filters.PHOTO, h.on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, h.on_document))
    app.add_handler(MessageHandler(filters.ANIMATION, h.on_animation))
    app.add_handler(MessageHandler(filters.VIDEO, h.on_video))
    app.add_handler(MessageHandler(filters.Sticker.ALL, h.on_sticker))
    app.add_handler(MessageHandler(filters.ALL, h.on_unknown))

    logger.info("Bot started — polling")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
