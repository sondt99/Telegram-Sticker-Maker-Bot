# Stickerify

Telegram bot that converts photos, GIFs, and videos into PNG + WebP (512px) sticker-ready files.

## Features

- **Photo / Image file** → PNG + WebP at 512px
- **GIF / Video** → static frame + animated WebP (≤256KB)
- **Sticker** → reconvert to PNG + WebP
- **Background removal** → `/rembg` toggle, powered by [rembg](https://github.com/danielgatis/rembg)
- **Batch convert** → send an album of photos, all converted at once

## Quick Start

```bash
cp .env.example .env
# Edit .env and paste your bot token
docker compose up -d --build
```

## Setup (without Docker)

### 1. Get a Bot Token
- Open Telegram, find **@BotFather**
- Send `/newbot` → name your bot → copy the **Bot Token**

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. (Optional) Install FFmpeg — for video/GIF support
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

### 4. Run
```bash
export BOT_TOKEN="your_token_here"
python -m stickerify
```

## Commands

| Command   | Description                         |
|-----------|-------------------------------------|
| `/start`  | Show usage instructions             |
| `/rembg`  | Toggle background removal on/off    |

## Usage

| You send           | Bot replies with                   |
|--------------------|------------------------------------|
| 🖼 Photo           | PNG + WebP 512px                   |
| 🖼 Album (batch)   | All photos converted at once       |
| 📎 Image file      | PNG + WebP 512px                   |
| 🎬 GIF             | PNG frame + Animated WebP (≤256KB) |
| 🎥 Short video     | PNG frame + Animated WebP (≤256KB) |
| 😀 Sticker         | PNG + WebP (reconverted)           |

## Telegram Sticker Specs

- **Static sticker:** PNG or WebP, longest side = 512px
- **Animated sticker:** Animated WebP, ≤ 256KB, ≤ 3 seconds

## Project Structure

```
stickerify/
├── config.py      — environment config (frozen dataclass)
├── converter.py   — image/video/rembg conversion
├── handlers.py    — Telegram message & album handlers
└── __main__.py    — entry point & bot wiring
```

## License

MIT
