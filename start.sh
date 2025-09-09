#!/bin/bash

# Скрипт запуска для Render.com

echo "🚀 Starting Heroku Userbot on Render..."

# Устанавливаем переменные окружения
export PYTHONPATH=/opt/render/project/src
export PYTHONUNBUFFERED=1

# Очищаем старые сессии
rm -f *.session
rm -f heroku-*.session

echo "🧹 Cleaned old sessions"

# Запускаем приложение
echo "▶️ Starting userbot..."
python -m heroku --port ${PORT:-5000}