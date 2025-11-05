FROM python:3.12-bullseye

# Используем российское зеркало только для apt
RUN sed -i 's|http://deb.debian.org/debian|http://mirror.yandex.ru/debian|g' /etc/apt/sources.list && \
    sed -i 's|http://security.debian.org/debian-security|http://mirror.yandex.ru/debian-security|g' /etc/apt/sources.list

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    libpq-dev \
    netcat-openbsd \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл зависимостей Python
COPY requirements.txt .
COPY packages /app/packages
COPY requirements.txt .
RUN pip install --no-index --find-links=/app/packages -r requirements.txt

# Копируем проект
COPY . .

# Копируем скрипты entrypoint и даём права на выполнение
COPY entrypoint_web.sh /entrypoint_web.sh
COPY entrypoint_celery.sh /entrypoint_celery.sh
RUN chmod +x /entrypoint_web.sh /entrypoint_celery.sh

# ENTRYPOINT оставляем в docker-compose
