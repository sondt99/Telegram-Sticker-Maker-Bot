# Stickerify

Telegram bot that prepares sticker-ready files from photos, GIFs, videos, and stickers.

## Features

- **Photo / Image file** → static PNG + WebP at 512px
- **GIF / Video** → static frame PNG + WebP, plus WEBM VP9 video sticker file when FFmpeg can fit Telegram limits
- **Sticker** → reconvert static/video stickers to PNG + WebP; TGS animated stickers are reported as unsupported
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

### 3. Install FFmpeg — required for video/GIF/WEBM support
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

FFmpeg must include `libvpx-vp9` for Telegram video sticker WEBM output.

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

| You send           | Bot replies with                                      |
|--------------------|-------------------------------------------------------|
| 🖼 Photo           | PNG + WebP 512px                                      |
| 🖼 Album (batch)   | All photos converted at once                          |
| 📎 Image file      | PNG + WebP 512px                                      |
| 🎬 GIF             | PNG/WebP static frame + WEBM VP9 video sticker file   |
| 🎥 Short video     | PNG/WebP static frame + WEBM VP9 video sticker file   |
| 😀 Static sticker  | Original PNG + PNG/WebP reconversion                  |
| 🎬 Video sticker   | Original WEBM + static PNG/WebP frame                 |
| ✨ TGS sticker     | Unsupported message                                   |

## Telegram Sticker Specs

- **Static sticker:** PNG or WebP, longest side = 512px.
- **Video sticker:** `.webm`, VP9, no audio, short duration, small file size. Stickerify targets 3 seconds and 256KB by default.
- **Animated sticker:** `.tgs` Lottie animation. Stickerify does not convert TGS yet.
- **Animated WebP is not a Telegram sticker-pack format.** GIF/video inputs are exported as WEBM VP9 for video sticker packs.

Telegram sticker packs are type-locked. A static pack can only contain static PNG/WebP stickers; a video pack can only contain WEBM video stickers. Create a separate video sticker pack with Telegram's sticker tooling when using generated `.webm` files.

Stickerify prepares files. It does not create or manage Telegram sticker packs yet.

## Configuration

Required:

```env
BOT_TOKEN=your_bot_token_here
```

Optional media settings:

```env
STICKER_SIZE=512
WEBP_QUALITY=90
VIDEO_MAX_BYTES=262144
VIDEO_DURATION=3
VIDEO_FPS=30
VIDEO_MIN_CRF=36
VIDEO_MAX_CRF=48
VIDEO_CRF_STEP=4
```

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
