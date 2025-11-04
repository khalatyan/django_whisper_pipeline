FROM python:3.12-bullseye

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    libpq-dev \
    netcat-openbsd \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Python зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем проект
COPY . .

# Копируем скрипты entrypoint для разных сервисов
COPY entrypoint_web.sh /entrypoint_web.sh
COPY entrypoint_celery.sh /entrypoint_celery.sh
RUN chmod +x /entrypoint_web.sh
RUN chmod +x /entrypoint_celery.sh

# НЕ указываем глобальный ENTRYPOINT
# ENTRYPOINT будем задавать в docker-compose
