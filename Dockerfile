# Render.com оптимизированный Dockerfile
FROM python:3.11-slim

# Устанавливаем системные зависимости включая git
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Копируем файлы требований
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Настраиваем Git глобально
RUN git config --global user.email "heroku@render.com" && \
    git config --global user.name "Heroku Userbot" && \
    git config --global init.defaultBranch main

# Создаем директорию для сессий
RUN mkdir -p /app/sessions

# Устанавливаем переменные окружения
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV DOCKER=true
ENV GIT_PYTHON_REFRESH=quiet

# Делаем start.sh исполняемым
RUN chmod +x start.sh

# Открываем порты
EXPOSE $PORT

# Команда запуска
CMD ["./start.sh"]