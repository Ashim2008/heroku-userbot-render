# Деплой Heroku Userbot на Render.com

## 🚀 Быстрый старт

### 1. Подготовка
1. Создайте аккаунт на [render.com](https://render.com)
2. Получите API ключи Telegram на [my.telegram.org/apps](https://my.telegram.org/apps)

### 2. Деплой на Render
1. **Подключите GitHub репозиторий** к Render.com
2. **Выберите "Web Service"**
3. **Настройте параметры:**
   - **Name**: heroku-userbot
   - **Environment**: Docker
   - **Build Command**: `docker build -t userbot .`
   - **Start Command**: `./start.sh`

### 3. Переменные окружения
В настройках Render добавьте:
```
API_ID=ваш_api_id
API_HASH=ваш_api_hash
PORT=5000
```

### 4. UptimeRobot настройка
- **URL для мониторинга**: `https://ваш-сервис.onrender.com/`
- **Интервал**: каждые 5 минут
- **Keyword monitoring**: "Хикка работает 24/7"

## ✅ Преимущества Render
- Стабильная работа 24/7
- Автоматические перезапуски при сбоях
- Бесплатный план (750 часов/месяц)
- Нет конфликтов сессий
- Лучше работает с keep_alive

## 🔧 Технические детали
- **Python**: 3.11
- **Порты**: 5000 (основной), 8080 (keep-alive)
- **Keep-alive**: встроенная система поддержания активности
- **Сессии**: автоматическая очистка при запуске

## 📞 Поддержка
Если что-то не работает:
1. Проверьте логи в Render Dashboard
2. Убедитесь, что API_ID и API_HASH корректны
3. Проверьте, что UptimeRobot настроен правильно