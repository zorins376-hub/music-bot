FROM python:3.12-slim

# Устанавливаем ffmpeg + curl (для deno) + build tools (для implicit/scipy)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl unzip build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем deno (JS-рантайм для yt-dlp signature solving)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh \
    && deno --version

# Node.js для сборки TMA Player фронтенда
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Собираем TMA Player фронтенд
RUN cd webapp/frontend && npm install && npx vite build

RUN mkdir -p /app/data /app/downloads /app/logs

CMD ["python", "-m", "bot.main"]
