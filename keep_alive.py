from flask import Flask
from threading import Thread
import time
import requests
import os
import logging

app = Flask('')
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/')
def home():
    return """
    <html>
    <head>
        <title>Heroku Userbot Keep-Alive</title>
        <meta name="description" content="Хикка работает 24/7">
    </head>
    <body>
        <h1>🤖 Heroku Userbot Keep-Alive</h1>
        <p><strong>Status:</strong> ✅ Online</p>
        <p><strong>Platform:</strong> Render.com Ready</p>
        <p><strong>Time:</strong> {}</p>
        <p>Хикка работает 24/7</p>
    </body>
    </html>
    """.format(time.strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/ping')
def ping():
    return "pong"

@app.route('/health')
def health():
    return {
        "status": "online",
        "uptime": "24/7",
        "service": "Heroku Userbot",
        "platform": "render-ready"
    }

@app.route('/status')
def status():
    return {
        "status": "online",
        "uptime": "24/7",
        "service": "Heroku Userbot"
    }

def run():
    # На Render.com не используем основной PORT, чтобы избежать конфликта с юзерботом
    if any(env_var in os.environ for env_var in ["RENDER", "RENDER_SERVICE_NAME", "RENDER_EXTERNAL_URL"]):
        port = 8080  # Используем фиксированный порт 8080 для keep-alive на Render
    else:
        port = int(os.environ.get('PORT', 8080))
        if port == 5000:  # Если основной порт занят
            port = 8080
    app.run(host="0.0.0.0", port=port, debug=False)

def self_ping():
    """Функция для самопинга каждые 5 минут"""
    while True:
        try:
            time.sleep(200)  # 5 минут
            
            # Для Render.com
            render_url = os.environ.get('RENDER_EXTERNAL_URL')
            replit_url = os.environ.get('REPL_SLUG')
            
            if render_url:
                url = render_url
            elif replit_url:
                url = f"https://{replit_url}.replit.dev/"
            else:
                # Попытка автоопределения
                service_name = os.environ.get('RENDER_SERVICE_NAME', 'userbot')
                url = f"https://{service_name}.onrender.com"
                
            print(f"🏓 Self-ping to: {url}")
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                print("✅ Self-ping successful")
            else:
                print(f"⚠️ Self-ping status: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Self-ping failed: {e}")

def keep_alive():
    # Запускаем Flask сервер
    server_thread = Thread(target=run)
    server_thread.daemon = True
    server_thread.start()
    
    # Запускаем самопинг
    ping_thread = Thread(target=self_ping)
    ping_thread.daemon = True
    ping_thread.start()
    
    print("🚀 Keep-alive server started for Render.com!")
