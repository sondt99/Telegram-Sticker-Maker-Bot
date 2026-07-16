FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home bot
WORKDIR /home/bot/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY stickerify/ stickerify/
RUN chown -R bot:bot /home/bot

USER bot
RUN python -c "from rembg import new_session; new_session('u2net')"

CMD ["python", "-u", "-m", "stickerify"]
