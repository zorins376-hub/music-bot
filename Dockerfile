FROM python:3.12-slim

# Устанавливаем ffmpeg, nodejs (для yt-dlp signature solving)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/downloads /app/logs

CMD ["python", "-m", "bot.main"]
