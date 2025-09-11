#!/bin/bash

# Скрипт запуска для Render.com с поддержкой голосового чата

echo "🚀 Starting Heroku Userbot with Voice Chat support on Render..."

# Устанавливаем переменные окружения
# PYTHONPATH уже установлен в Dockerfile для Docker контейнера
export PYTHONUNBUFFERED=1
export FFMPEG_BINARY=/usr/bin/ffmpeg

# Проверяем наличие API ключей для неинтерактивного запуска
if [ -n "$VOICE_CHAT_API_ID" ] && [ -n "$VOICE_CHAT_API_HASH" ]; then
    echo "✅ Voice chat API credentials found"
    export API_ID=$VOICE_CHAT_API_ID
    export API_HASH=$VOICE_CHAT_API_HASH
    if [ -n "$VOICE_CHAT_SESSION_STRING" ]; then
        export SESSION_STRING=$VOICE_CHAT_SESSION_STRING
        echo "✅ Session string provided"
    fi
elif [ -n "$BOT_TOKEN" ]; then
    echo "✅ Bot token provided for bot mode"
else
    echo "⚠️ No API credentials provided - will require interactive setup"
    echo "   Set VOICE_CHAT_API_ID and VOICE_CHAT_API_HASH environment variables"
    echo "   or BOT_TOKEN for bot mode"
fi

# Проверяем наличие ffmpeg для голосового чата
echo "🎵 Checking voice chat dependencies..."
if command -v ffmpeg &> /dev/null; then
    echo "✅ FFmpeg found: $(ffmpeg -version | head -n1)"
else
    echo "❌ FFmpeg not found! Voice chat will not work."
fi

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

# Создаем необходимые директории
mkdir -p /app/sessions /app/temp

# Проверяем Python зависимости для голосового чата
echo "🔍 Checking voice chat Python dependencies..."
python3 -c "
try:
    import pyrogram, yt_dlp, aiohttp, ffmpeg
    print('✅ All voice chat dependencies available')
except ImportError as e:
    print(f'⚠️ Missing dependency: {e}')
" 2>/dev/null || echo "⚠️ Some voice chat dependencies may be missing"

# Запускаем приложение
echo "▶️ Starting userbot with voice chat support..."
# Для Render.com используем переменную PORT
if [ ! -z "$RENDER" ] || [ ! -z "$RENDER_SERVICE_NAME" ] || [ ! -z "$RENDER_EXTERNAL_URL" ]; then
    echo "🌐 Detected Render.com environment"
    python -m heroku --port ${PORT:-10000}
else
    python -m heroku --port ${PORT:-10000}
fi