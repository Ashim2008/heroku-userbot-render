# Render.com оптимизированный Dockerfile с поддержкой голосового чата
FROM python:3.11-slim

# Устанавливаем системные зависимости включая git и ffmpeg для голосового чата
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    git \
    curl \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Копируем файлы требований из render-deploy
COPY render-deploy/requirements.txt ./requirements.txt

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Настраиваем Git глобально
RUN git config --global user.email "heroku@render.com" && \
    git config --global user.name "Heroku Userbot" && \
    git config --global init.defaultBranch main

# Создаем директории для сессий и временных файлов
RUN mkdir -p /app/sessions /app/temp

# Устанавливаем переменные окружения
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV DOCKER=true
ENV GIT_PYTHON_REFRESH=quiet
ENV FFMPEG_BINARY=/usr/bin/ffmpeg

# Делаем render-deploy/start.sh исполняемым
RUN chmod +x render-deploy/start.sh

# Открываем порты
EXPOSE 10000

# Команда запуска - используем обновленный скрипт
CMD ["bash", "render-deploy/start.sh"]