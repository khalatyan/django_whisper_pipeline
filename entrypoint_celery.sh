#!/bin/bash
set -e
# Ждём базу
until nc -z "$POSTGRES_HOST" "$POSTGRES_PORT"; do sleep 1; done

# Просто запускаем команду (worker или beat)
exec "$@"
