FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home bot
WORKDIR /home/bot/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY stickerify/ stickerify/

USER bot

CMD ["python", "-u", "-m", "stickerify"]
