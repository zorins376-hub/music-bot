FROM python:3.12-slim

# Устанавливаем ffmpeg + curl (для deno)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl unzip \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем deno (JS-рантайм для yt-dlp signature solving)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh \
    && deno --version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/downloads /app/logs

CMD ["python", "-m", "bot.main"]
