#!/bin/bash

# Скрипт запуска для Render.com

echo "🚀 Starting Heroku Userbot on Render..."

# Устанавливаем переменные окружения
export PYTHONPATH=/opt/render/project/src
export PYTHONUNBUFFERED=1

# Проверяем и настраиваем Git
echo "🔧 Setting up Git..."
if ! command -v git &> /dev/null; then
    echo "❌ Git not found! Installing..."
    apt-get update && apt-get install -y git
fi

# Настраиваем Git (необходимо для работы updater.py)
git config --global user.email "heroku@render.com" 2>/dev/null || true
git config --global user.name "Heroku Userbot" 2>/dev/null || true

# Инициализируем git репозиторий если его нет
if [ ! -d ".git" ]; then
    echo "📦 Initializing Git repository..."
    git init
    git remote add origin https://github.com/coddrago/Heroku.git 2>/dev/null || true
    git fetch origin 2>/dev/null || echo "⚠️ Could not fetch from origin (this is normal for Render)"
fi

echo "✅ Git setup complete"

# Запускаем приложение
echo "▶️ Starting userbot..."
# Для Render.com используем переменную PORT
if [ ! -z "$RENDER" ] || [ ! -z "$RENDER_SERVICE_NAME" ] || [ ! -z "$RENDER_EXTERNAL_URL" ]; then
    echo "🌐 Detected Render.com environment"
    python -m heroku --port ${PORT:-80}
else
    python -m heroku --port ${PORT:-80}
fi
