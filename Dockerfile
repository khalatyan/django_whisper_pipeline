FROM python:3.12-bullseye

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Используем официальные зеркала (возвращаем исходные)
RUN sed -i 's|http://mirror.yandex.ru/debian|http://deb.debian.org/debian|g' /etc/apt/sources.list && \
    sed -i 's|http://mirror.yandex.ru/debian-security|http://security.debian.org/debian-security|g' /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
        libpq-dev \
        netcat-openbsd \
        cron \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY packages /app/packages
RUN pip install --no-index --find-links=/app/packages -r requirements.txt

COPY . .

COPY entrypoint_web.sh /entrypoint_web.sh
COPY entrypoint_celery.sh /entrypoint_celery.sh
RUN chmod +x /entrypoint_web.sh /entrypoint_celery.sh
