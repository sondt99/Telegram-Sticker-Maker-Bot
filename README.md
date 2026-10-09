# Stickerify

Telegram bot that prepares sticker-ready files from photos, GIFs, videos, and stickers.

## Features

- **Photo / Image file** → validated static PNG + WebP at 512px
- **GIF / Video** → static frame PNG + WebP, plus verified WEBM VP9 video sticker file when FFmpeg/FFprobe can fit Telegram limits
- **Sticker** → reconvert static/video stickers to PNG + WebP; TGS animated stickers are reported as unsupported
- **Background removal** → `/rembg` toggle for photos, image files, static stickers, and photo albums
- **Batch convert** → send a photo album, all valid photos converted with per-item failure handling

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

### 2. Install runtime dependencies
```bash
pip install -r requirements.txt
```

For development and tests:

```bash
pip install -r requirements-dev.txt
```

### 3. Install FFmpeg — required for video/GIF/WEBM support
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

FFmpeg must include `libvpx-vp9`, and `ffprobe` must be available to verify Telegram video sticker output.

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
| 🖼 Photo           | PNG + WebP 512px, with size warnings if needed        |
| 🖼 Photo album     | All valid photos converted; failures summarized       |
| 📎 Image file      | PNG + WebP 512px                                      |
| 🎬 GIF             | PNG/WebP static frame + verified WEBM VP9 if valid    |
| 🎥 Short video     | PNG/WebP static frame + verified WEBM VP9 if valid    |
| 😀 Static sticker  | Original PNG + PNG/WebP reconversion                  |
| 🎬 Video sticker   | Original WEBM + static PNG/WebP frame                 |
| ✨ TGS sticker     | Unsupported message                                   |

## Telegram Sticker Specs

- **Static sticker:** PNG or WebP, 512px sticker canvas, max 512KB.
- **Video sticker:** `.webm`, VP9, no audio, max 256KB, max 3 seconds, max 30 FPS, 512px canvas.
- **Animated sticker:** `.tgs` Lottie animation. Stickerify does not convert TGS yet.
- **Animated WebP is not a Telegram sticker-pack format.** GIF/video inputs are exported as WEBM VP9 for video sticker packs.

Telegram sticker packs are type-locked. A static pack can only contain static PNG/WebP stickers; a video pack can only contain WEBM video stickers. Create a separate video sticker pack with Telegram's sticker tooling when using generated `.webm` files.

Stickerify prepares files. It does not create or manage Telegram sticker packs yet.

## Configuration

Required:

```env
BOT_TOKEN=your_bot_token_here
```

Optional Telegram-safe media settings:

```env
STICKER_SIZE=512
WEBP_QUALITY=90
STATIC_MAX_BYTES=524288
VIDEO_MAX_BYTES=262144
VIDEO_DURATION=3
VIDEO_FPS=30
VIDEO_MIN_CRF=36
VIDEO_MAX_CRF=48
VIDEO_CRF_STEP=4
```

`STICKER_SIZE`, `STATIC_MAX_BYTES`, `VIDEO_MAX_BYTES`, `VIDEO_DURATION`, and `VIDEO_FPS` are capped to Telegram sticker limits. Invalid values fail at startup.

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m compileall stickerify tests
python -m pytest -q
```

Docker smoke checks:

```bash
docker build -t stickerify:test .
docker run --rm --entrypoint python stickerify:test -c "import shutil; assert shutil.which('ffmpeg'); assert shutil.which('ffprobe')"
```

## Project Structure

```
stickerify/config.py     — environment config and Telegram limits
stickerify/converter.py  — image/video/rembg conversion and validation
stickerify/handlers.py   — Telegram message & album handlers
stickerify/__main__.py   — entry point & bot wiring
tests/                   — pytest coverage for config, converter, and handlers
Dockerfile               — container image
docker-compose.yml       — local deployment
.env.example             — environment template
requirements.txt         — runtime dependencies
requirements-dev.txt     — test and dev dependencies
```

## License

MIT
