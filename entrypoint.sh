#!/bin/bash
set -e

# Ждём базу
until nc -z "$POSTGRES_HOST" "$POSTGRES_PORT"; do
  echo "Waiting for Postgres..."
  sleep 1
done

echo "Postgres доступен, выполняем миграции..."
python manage.py migrate --noinput
python manage.py collectstatic --noinput

echo "Создаём суперпользователя, если его нет..."
python manage.py shell <<END
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username="${DJANGO_SUPERUSER_USERNAME:-admin}").exists():
    User.objects.create_superuser(
        "${DJANGO_SUPERUSER_USERNAME:-admin}",
        "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}",
        "${DJANGO_SUPERUSER_PASSWORD:-adminpass}"
    )
END

exec "$@"
