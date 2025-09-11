# 🚀 Render.com Deployment для Heroku Userbot с Voice Chat

## 📋 Быстрый старт

### 1. **Подготовка Telegram API ключей**
Получите API ключи на [my.telegram.org/apps](https://my.telegram.org/apps):
- `API_ID` - ваш ID приложения
- `API_HASH` - ваш хэш приложения

### 2. **Настройка переменных окружения в Render**
В дашборде Render добавьте:
```
VOICE_CHAT_API_ID = ваш_api_id
VOICE_CHAT_API_HASH = ваш_api_hash
```

### 3. **Деплой файлы готовы!**
- ✅ `Dockerfile` - Docker контейнер с ffmpeg
- ✅ `requirements.txt` - все зависимости голосового чата  
- ✅ `start.sh` - стартовый скрипт с проверками
- ✅ `render.yaml` - конфигурация сервиса

## 🎵 Voice Chat команды
После деплоя доступны команды:
- `.vcsetup` - настройка голосового чата
- `.addm <URL>` - добавить аудио
- `.addv <URL>` - добавить видео
- `.pause/.resume/.stop` - управление
- `.queue` - показать очередь

## 🔧 Режимы работы

### Docker режим (рекомендуется)
Использует `render.yaml` с `env: docker` и `Dockerfile`

### Native режим (альтернатива)
Для native режима замените в `render.yaml`:
```yaml
env: python
buildCommand: |
  apt-get update && apt-get install -y ffmpeg libavcodec-dev libavformat-dev libavutil-dev libswscale-dev libswresample-dev &&
  pip install -r render-deploy/requirements.txt
startCommand: bash render-deploy/start.sh
```

## 📚 Зависимости
- **ffmpeg** - аудио/видео обработка
- **pyrogram** - Telegram клиент
- **py-tgcalls** - голосовые чаты  
- **yt-dlp** - YouTube загрузка