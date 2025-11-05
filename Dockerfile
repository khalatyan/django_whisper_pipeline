FROM python:3.12-bullseye

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Используем официальные зеркала (возвращаем исходные)
RUN echo "deb [trusted=yes] http://mirror.yandex.ru/debian bullseye main contrib non-free" > /etc/apt/sources.list && \
    echo "deb [trusted=yes] http://mirror.yandex.ru/debian-security bullseye-security main contrib non-free" >> /etc/apt/sources.list && \
    echo "deb [trusted=yes] http://mirror.yandex.ru/debian bullseye-updates main contrib non-free" >> /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        libcairo2-dev \
        gir1.2-pango-1.0 \
        python3-dev \
        ffmpeg \
        libpq-dev \
        netcat-openbsd \
        ninja-build \
        cron \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY packages /app/packages
RUN pip install --no-index --find-links=/app/packages -r requirements.txt

COPY . .

COPY entrypoint_web.sh /entrypoint_web.sh
COPY entrypoint_celery.sh /entrypoint_celery.sh
RUN chmod +x /entrypoint_web.sh /entrypoint_celery.sh
