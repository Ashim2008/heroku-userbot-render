# ©️ Dan Gazizullin, 2021-2023
# This file is a part of Heroku Userbot
# Code is NOT licensed under any license
# 🔒 Licensed only for Heroku Userbot
# 🌐 https://github.com/hikariatama/Heroku

"""
🎵 Native Voice Chat Module for Heroku Userbot
Works directly with Heroku's CustomTelegramClient using hybrid architecture:
- Heroku userbot handles commands, queues, and UI
- Separate Pyrogram backend handles media streaming via PyTgCalls
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import tempfile
import time
import typing
from dataclasses import dataclass, asdict
from pathlib import Path

from .. import loader, utils

# Импорт зависимостей для стриминга
STREAMING_AVAILABLE = True
STREAMING_ERROR = None

try:
    import pyrogram
    from pyrogram import Client as PyrogramClient
    from pyrogram.errors import AuthKeyUnregistered, SessionPasswordNeeded
    logging.info("✅ Pyrogram imports successful")
except ImportError as e:
    STREAMING_AVAILABLE = False
    STREAMING_ERROR = f"Pyrogram not installed: {e}"
    logging.error(f"❌ Pyrogram import failed: {e}")

try:
    from pytgcalls import PyTgCalls
    from pytgcalls.exceptions import NoActiveGroupCall, NotInCallError
    logging.info("✅ PyTgCalls imports successful")
except ImportError as e:
    STREAMING_AVAILABLE = False
    STREAMING_ERROR = f"PyTgCalls not installed: {e}"
    logging.error(f"❌ PyTgCalls import failed: {e}")

try:
    import yt_dlp
    from yt_dlp import YoutubeDL
    YT_DLP_AVAILABLE = True
    logging.info("✅ yt-dlp imports successful")
except ImportError as e:
    YT_DLP_AVAILABLE = False
    logging.error(f"❌ yt-dlp import failed: {e}")

try:
    import ffmpeg
    # Проверяем доступность ffmpeg binary
    import subprocess
    subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    FFMPEG_AVAILABLE = True
    logging.info("✅ ffmpeg binary and python package available")
except (ImportError, subprocess.CalledProcessError, FileNotFoundError) as e:
    FFMPEG_AVAILABLE = False
    logging.error(f"❌ ffmpeg not available: {e}")


@dataclass
class QueueItem:
    """Элемент очереди воспроизведения"""
    file_path: str
    title: str
    duration: int = 0
    is_video: bool = False
    source_type: str = "unknown"  # youtube, url, telegram, file
    added_by: int = 0
    timestamp: float = 0
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "QueueItem":
        return cls(**data)


class TempFileManager:
    """Менеджер временных файлов с автоочисткой"""
    
    def __init__(self):
        self._temp_files: typing.Set[str] = set()
        self._cleanup_task = None
        
    def create_temp_file(self, suffix: str = "") -> str:
        """Создать временный файл с отслеживанием"""
        # Use NamedTemporaryFile instead of mktemp for security
        temp_fd = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        temp_file = temp_fd.name
        temp_fd.close()  # Close the file descriptor, but keep the file
        self._temp_files.add(temp_file)
        return temp_file
    
    def cleanup_file(self, file_path: str):
        """Удалить конкретный файл"""
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
            self._temp_files.discard(file_path)
        except Exception as e:
            logging.error(f"❌ Error cleaning temp file {file_path}: {e}")
    
    def cleanup_all(self):
        """Очистить все временные файлы"""
        for file_path in list(self._temp_files):
            self.cleanup_file(file_path)
        self._temp_files.clear()


class QueueManager:
    """Менеджер очередей для каждого чата"""
    
    def __init__(self, db):
        self.db = db
        self._queues: typing.Dict[int, typing.List[QueueItem]] = {}
        self._current_playing: typing.Dict[int, int] = {}  # chat_id -> queue_index
        self._repeat_mode: typing.Dict[int, bool] = {}
        
    async def load_queues(self):
        """Загрузка очередей из базы данных"""
        try:
            data = self.db.get("VoiceChatNative", "queues", {})
            for chat_id_str, queue_data in data.items():
                chat_id = int(chat_id_str)
                self._queues[chat_id] = [
                    QueueItem.from_dict(item_data) 
                    for item_data in queue_data.get("items", [])
                ]
                self._current_playing[chat_id] = queue_data.get("current", 0)
                self._repeat_mode[chat_id] = queue_data.get("repeat", False)
            logging.info(f"✅ Loaded {len(self._queues)} queues from database")
        except Exception as e:
            logging.error(f"❌ Error loading queues: {e}")
    
    async def save_queues(self):
        """Сохранение очередей в базу данных"""
        try:
            data = {}
            for chat_id, queue in self._queues.items():
                if queue:  # Сохраняем только непустые очереди
                    data[str(chat_id)] = {
                        "items": [item.to_dict() for item in queue],
                        "current": self._current_playing.get(chat_id, 0),
                        "repeat": self._repeat_mode.get(chat_id, False)
                    }
            self.db.set("VoiceChatNative", "queues", data)
            logging.info(f"✅ Saved {len(data)} queues to database")
        except Exception as e:
            logging.error(f"❌ Error saving queues: {e}")
    
    def add_item(self, chat_id: int, item: QueueItem) -> int:
        """Добавить элемент в очередь"""
        if chat_id not in self._queues:
            self._queues[chat_id] = []
        
        item.timestamp = time.time()
        self._queues[chat_id].append(item)
        return len(self._queues[chat_id])
    
    def get_queue(self, chat_id: int) -> typing.List[QueueItem]:
        """Получить очередь чата"""
        return self._queues.get(chat_id, [])
    
    def get_current(self, chat_id: int) -> typing.Optional[QueueItem]:
        """Получить текущий элемент очереди"""
        queue = self.get_queue(chat_id)
        current_index = self._current_playing.get(chat_id, 0)
        
        if queue and 0 <= current_index < len(queue):
            return queue[current_index]
        return None
    
    def next_item(self, chat_id: int) -> typing.Optional[QueueItem]:
        """Перейти к следующему элементу"""
        queue = self.get_queue(chat_id)
        if not queue:
            return None
        
        current_index = self._current_playing.get(chat_id, 0)
        next_index = current_index + 1
        
        # Проверяем режим повтора
        if next_index >= len(queue):
            if self._repeat_mode.get(chat_id, False):
                next_index = 0  # Начинаем сначала
            else:
                return None  # Очередь закончилась
        
        self._current_playing[chat_id] = next_index
        return queue[next_index]
    
    def clear_queue(self, chat_id: int):
        """Очистить очередь чата"""
        self._queues.pop(chat_id, None)
        self._current_playing.pop(chat_id, None)
    
    def set_repeat(self, chat_id: int, enabled: bool):
        """Установить режим повтора"""
        self._repeat_mode[chat_id] = enabled
    
    def is_repeat_enabled(self, chat_id: int) -> bool:
        """Проверить включен ли режим повтора"""
        return self._repeat_mode.get(chat_id, False)


class SourceResolver:
    """Базовый класс для обработки источников медиа"""
    
    def __init__(self, temp_manager):
        self.temp_manager = temp_manager
    
    async def resolve(self, source: str, metadata: dict = None) -> typing.Optional[QueueItem]:
        """Обработать источник и вернуть QueueItem"""
        raise NotImplementedError


class YouTubeSourceResolver(SourceResolver):
    """Resolver для YouTube видео и музыки"""
    
    async def resolve(self, url: str, metadata: dict = None) -> typing.Optional[QueueItem]:
        if not YT_DLP_AVAILABLE:
            logging.error("❌ yt-dlp not available")
            return None
        
        if not FFMPEG_AVAILABLE:
            logging.error("❌ ffmpeg not available for audio processing")
            return None
        
        temp_file = None
        try:
            # Создаем временный файл
            temp_file = self.temp_manager.create_temp_file(".mp3")
            
            # Настройки yt-dlp для лучшего качества аудио
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': temp_file.replace('.mp3', '.%(ext)s'),  # Позволяем yt-dlp выбрать расширение
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'extractaudio': True,
                'audioformat': 'mp3',
                'audioquality': '192',
                'max_filesize': 50 * 1024 * 1024,  # 50MB лимит
            }
            
            with YoutubeDL(ydl_opts) as ydl:
                # Получаем информацию о видео
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'Unknown')
                duration = info.get('duration', 0)
                
                # Проверяем длительность
                if duration > 3600:  # 1 час лимит
                    logging.error(f"❌ Video too long: {duration}s")
                    return None
                
                # Скачиваем файл
                ydl.download([url])
                
                # Находим скачанный файл (может быть с другим расширением)
                import glob
                base_path = temp_file.replace('.mp3', '')
                downloaded_files = glob.glob(f"{base_path}.*")
                
                if downloaded_files:
                    actual_file = downloaded_files[0]
                    # Переименовываем в .mp3 если нужно
                    if not actual_file.endswith('.mp3'):
                        os.rename(actual_file, temp_file)
                        actual_file = temp_file
                else:
                    actual_file = temp_file
                
                return QueueItem(
                    file_path=actual_file,
                    title=title,
                    duration=duration,
                    is_video=False,  # Всегда аудио для YouTube
                    source_type="youtube",
                    added_by=metadata.get('user_id', 0) if metadata else 0
                )
                
        except Exception as e:
            logging.error(f"❌ YouTube resolve error: {e}")
            # Очищаем temp файл при ошибке
            if temp_file and os.path.exists(temp_file):
                self.temp_manager.cleanup_file(temp_file)
            return None


class DirectURLSourceResolver(SourceResolver):
    """Resolver для прямых URL ссылок на медиа файлы"""
    
    async def resolve(self, url: str, metadata: dict = None) -> typing.Optional[QueueItem]:
        temp_file = None
        
        try:
            import aiohttp
            
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60)  # 60 секунд лимит
            ) as session:
                # Сначала делаем HEAD запрос для проверки размера
                try:
                    async with session.head(url) as head_response:
                        if head_response.status != 200:
                            logging.error(f"❌ URL not accessible: {head_response.status}")
                            return None
                        
                        # Проверяем размер файла
                        content_length = head_response.headers.get('content-length')
                        if content_length:
                            size_mb = int(content_length) / (1024 * 1024)
                            if size_mb > 100:  # 100MB лимит
                                logging.error(f"❌ File too large: {size_mb:.1f}MB")
                                return None
                        
                        content_type = head_response.headers.get('content-type', '').lower()
                except Exception:
                    # Если HEAD не работает, продолжаем с GET
                    content_type = ''
                
                # Определяем расширение файла и создаем правильный temp файл
                is_video = 'video' in content_type
                
                if 'audio' in content_type:
                    if 'mp3' in content_type:
                        temp_file = self.temp_manager.create_temp_file('.mp3')
                    elif 'ogg' in content_type:
                        temp_file = self.temp_manager.create_temp_file('.ogg')
                    else:
                        temp_file = self.temp_manager.create_temp_file('.m4a')
                elif 'video' in content_type:
                    if 'mp4' in content_type:
                        temp_file = self.temp_manager.create_temp_file('.mp4')
                    else:
                        temp_file = self.temp_manager.create_temp_file('.mkv')
                else:
                    # Неизвестный тип, создаем базовый файл
                    temp_file = self.temp_manager.create_temp_file()
                
                # Скачиваем файл с контролем размера
                downloaded_size = 0
                max_size = 100 * 1024 * 1024  # 100MB
                
                async with session.get(url) as response:
                    if response.status == 200:
                        with open(temp_file, 'wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                downloaded_size += len(chunk)
                                if downloaded_size > max_size:
                                    raise Exception(f"File too large (>{max_size/(1024*1024):.1f}MB)")
                                f.write(chunk)
                        
                        # Получаем название из URL или заголовков
                        title = metadata.get('title') if metadata else None
                        if not title:
                            title = url.split('/')[-1]
                            if '?' in title:
                                title = title.split('?')[0]
                            if not title or title == '/':
                                title = "Downloaded Media"
                        
                        return QueueItem(
                            file_path=temp_file,
                            title=title,
                            duration=0,  # Длительность неизвестна
                            is_video=is_video,
                            source_type="url",
                            added_by=metadata.get('user_id', 0) if metadata else 0
                        )
                    else:
                        logging.error(f"❌ HTTP error {response.status}")
                        return None
                        
        except Exception as e:
            logging.error(f"❌ Direct URL resolve error: {e}")
            # Очищаем temp файлы при ошибке
            if temp_file and os.path.exists(temp_file):
                self.temp_manager.cleanup_file(temp_file)
            return None


class TelegramMediaSourceResolver(SourceResolver):
    """Resolver для медиа файлов из Telegram"""
    
    def __init__(self, temp_manager, client):
        super().__init__(temp_manager)
        self.client = client
    
    async def resolve(self, message, metadata: dict = None) -> typing.Optional[QueueItem]:
        temp_file = None
        
        try:
            if not message or not message.media:
                return None
            
            # Проверяем размер файла (ограничение 200MB для Telegram)
            file_size = 0
            if hasattr(message, 'document') and message.document:
                file_size = getattr(message.document, 'size', 0)
            elif hasattr(message, 'audio') and message.audio:
                file_size = getattr(message.audio, 'size', 0)
            elif hasattr(message, 'video') and message.video:
                file_size = getattr(message.video, 'size', 0)
            
            if file_size > 200 * 1024 * 1024:  # 200MB лимит
                logging.error(f"❌ Telegram file too large: {file_size/(1024*1024):.1f}MB")
                return None
            
            # Определяем тип и создаем временный файл
            duration = 0
            title = "Unknown"
            is_video = False
            
            if hasattr(message, 'document') and message.document:
                # Документ (аудио/видео файл)
                mime_type = getattr(message.document, 'mime_type', '')
                is_video = mime_type.startswith('video/')
                
                if mime_type.endswith('/mp3') or 'audio/mp3' in mime_type:
                    temp_file = self.temp_manager.create_temp_file('.mp3')
                elif mime_type.endswith('/ogg') or 'audio/ogg' in mime_type:
                    temp_file = self.temp_manager.create_temp_file('.ogg')
                elif mime_type.endswith('/mp4') or 'video/mp4' in mime_type:
                    temp_file = self.temp_manager.create_temp_file('.mp4')
                    is_video = True
                else:
                    temp_file = self.temp_manager.create_temp_file()
                
                # Извлекаем информацию из атрибутов
                if hasattr(message.document, 'attributes'):
                    for attr in message.document.attributes:
                        if hasattr(attr, 'title') and attr.title:
                            title = attr.title
                        elif hasattr(attr, 'file_name') and attr.file_name:
                            title = attr.file_name
                        elif hasattr(attr, 'duration'):
                            duration = getattr(attr, 'duration', 0)
                        elif hasattr(attr, 'performer') and hasattr(attr, 'title'):
                            title = f"{attr.performer} - {attr.title}"
                            
            elif hasattr(message, 'audio') and message.audio:
                # Аудио файл
                temp_file = self.temp_manager.create_temp_file('.mp3')
                duration = getattr(message.audio, 'duration', 0)
                title = getattr(message.audio, 'title', 'Audio')
                if hasattr(message.audio, 'performer') and message.audio.performer:
                    title = f"{message.audio.performer} - {title}"
            
            elif hasattr(message, 'video') and message.video:
                # Видео файл
                temp_file = self.temp_manager.create_temp_file('.mp4')
                duration = getattr(message.video, 'duration', 0)
                title = "Video"
                is_video = True
                
            if not temp_file:
                return None
            
            # Скачиваем файл
            await self.client.download_media(message, temp_file)
            
            return QueueItem(
                file_path=temp_file,
                title=title,
                duration=duration,
                is_video=is_video,
                source_type="telegram",
                added_by=metadata.get('user_id', 0) if metadata else 0
            )
            
        except Exception as e:
            logging.error(f"❌ Telegram media resolve error: {e}")
            if temp_file and os.path.exists(temp_file):
                self.temp_manager.cleanup_file(temp_file)
            return None


class PyrogramTgCallsBackend:
    """Pyrogram + PyTgCalls backend для стриминга"""
    
    def __init__(self):
        self.client = None
        self.pytgcalls = None
        self.is_initialized = False
        self.active_calls = {}  # chat_id -> call_info
    
    async def initialize(self, api_id: int, api_hash: str, session_string: str = None):
        """Инициализация Pyrogram клиента и PyTgCalls"""
        try:
            if not STREAMING_AVAILABLE:
                raise Exception(f"Streaming not available: {STREAMING_ERROR}")
            
            # Инициализация Pyrogram клиента
            if session_string:
                self.client = PyrogramClient(
                    "voicechat_session", 
                    api_id=api_id, 
                    api_hash=api_hash,
                    session_string=session_string,
                    no_updates=False
                )
            else:
                self.client = PyrogramClient(
                    "voicechat_session",
                    api_id=api_id,
                    api_hash=api_hash,
                    no_updates=False
                )
            
            await self.client.start()
            logging.info("✅ Pyrogram client started")
            
            # Инициализация PyTgCalls
            self.pytgcalls = PyTgCalls(self.client)
            await self.pytgcalls.start()
            logging.info("✅ PyTgCalls started")
            
            self.is_initialized = True
            return True
            
        except Exception as e:
            logging.error(f"❌ Backend initialization failed: {e}")
            await self.cleanup()
            return False
    
    
    async def join_voice_chat(self, chat_id: int) -> bool:
        """Присоединиться к голосовому чату"""
        try:
            if not self.is_initialized:
                logging.error("❌ Backend not initialized")
                return False
            
            if chat_id in self.active_calls:
                logging.info(f"✅ Already in voice chat {chat_id}")
                return True
            
            try:
                # Современный PyTgCalls API
                from pytgcalls.types import AudioParameters
                await self.pytgcalls.join_group_call(
                    chat_id,
                    AudioParameters()
                )
            except Exception as e:
                # Fallback для старых версий API
                try:
                    await self.pytgcalls.join_group_call(chat_id)
                except:
                    if hasattr(self.pytgcalls, 'join_group_call'):
                        await self.pytgcalls.join_group_call(chat_id, "")
                    else:
                        raise e
            
            self.active_calls[chat_id] = {
                'joined_at': time.time(),
                'current_stream': None,
                'is_paused': False
            }
            
            logging.info(f"✅ Joined voice chat {chat_id}")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to join voice chat {chat_id}: {e}")
            return False
    
    async def leave_voice_chat(self, chat_id: int) -> bool:
        """Покинуть голосовой чат"""
        try:
            if chat_id not in self.active_calls:
                return True
            
            try:
                await self.pytgcalls.leave_group_call(chat_id)
            except Exception as e:
                logging.warning(f"⚠️ Error leaving call (may be already left): {e}")
            
            self.active_calls.pop(chat_id, None)
            
            logging.info(f"✅ Left voice chat {chat_id}")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to leave voice chat {chat_id}: {e}")
            return False
    
    async def play_media(self, chat_id: int, file_path: str, is_video: bool = False, quality: str = "medium") -> bool:
        """Воспроизвести медиа файл"""
        try:
            if not self.is_initialized:
                logging.error("❌ Backend not initialized")
                return False
            
            if not os.path.exists(file_path):
                logging.error(f"❌ Media file not found: {file_path}")
                return False
            
            # Современный PyTgCalls API - подключение происходит через join_group_call с потоком
            # Поэтому просто отмечаем что готовы к работе с чатом
            
            # Современный PyTgCalls API
            try:
                from pytgcalls.types import AudioPiped, VideoPiped, AudioParameters, VideoParameters
                
                if chat_id in self.active_calls and self.active_calls[chat_id].get('current_stream'):
                    # Переключение на новый трек
                    if is_video:
                        stream = VideoPiped(file_path)
                        await self.pytgcalls.change_stream(
                            chat_id,
                            stream,
                            video_parameters=VideoParameters.from_quality("medium"),
                            audio_parameters=AudioParameters.from_quality("medium")
                        )
                    else:
                        stream = AudioPiped(file_path)
                        await self.pytgcalls.change_stream(
                            chat_id,
                            stream,
                            audio_parameters=AudioParameters.from_quality(quality)
                        )
                else:
                    # Первое подключение к голосовому чату
                    if is_video:
                        stream = VideoPiped(file_path)
                        await self.pytgcalls.join_group_call(
                            chat_id,
                            stream,
                            video_parameters=VideoParameters.from_quality("medium"),
                            audio_parameters=AudioParameters.from_quality("medium")
                        )
                    else:
                        stream = AudioPiped(file_path)
                        await self.pytgcalls.join_group_call(
                            chat_id,
                            stream,
                            audio_parameters=AudioParameters.from_quality(quality)
                        )
                    
                    # Отмечаем что подключились
                    self.active_calls[chat_id] = {
                        'joined_at': time.time(),
                        'current_stream': file_path,
                        'is_paused': False,
                    }
                    
            except (ImportError, AttributeError) as e:
                logging.error(f"❌ PyTgCalls API error: {e}")
                return False
            
            # Обновляем информацию о текущем стриме
            if chat_id in self.active_calls:
                self.active_calls[chat_id]['current_stream'] = file_path
                self.active_calls[chat_id]['is_paused'] = False
            
            logging.info(f"🎵 Started playing: {os.path.basename(file_path)} in chat {chat_id}")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to play media in chat {chat_id}: {e}")
            return False
    
    async def pause_stream(self, chat_id: int) -> bool:
        """Поставить стрим на паузу"""
        try:
            if chat_id not in self.active_calls:
                return False
            
            if hasattr(self.pytgcalls, 'pause_stream'):
                await self.pytgcalls.pause_stream(chat_id)
            else:
                logging.warning("⚠️ Pause not supported by PyTgCalls version")
                return False
            
            self.active_calls[chat_id]['is_paused'] = True
            logging.info(f"⏸️ Paused stream in chat {chat_id}")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to pause stream in chat {chat_id}: {e}")
            return False
    
    async def resume_stream(self, chat_id: int) -> bool:
        """Возобновить стрим"""
        try:
            if chat_id not in self.active_calls:
                return False
            
            if hasattr(self.pytgcalls, 'resume_stream'):
                await self.pytgcalls.resume_stream(chat_id)
            else:
                logging.warning("⚠️ Resume not supported by PyTgCalls version")
                return False
                
            self.active_calls[chat_id]['is_paused'] = False
            logging.info(f"▶️ Resumed stream in chat {chat_id}")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to resume stream in chat {chat_id}: {e}")
            return False
    
    async def stop_stream(self, chat_id: int) -> bool:
        """Остановить стрим"""
        try:
            if chat_id not in self.active_calls:
                return False
            
            # Останавливаем текущий стрим и покидаем чат
            await self.leave_voice_chat(chat_id)
            
            logging.info(f"⏹️ Stopped stream in chat {chat_id}")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to stop stream in chat {chat_id}: {e}")
            return False
    
    def is_in_call(self, chat_id: int) -> bool:
        """Проверить находимся ли в голосовом чате"""
        return chat_id in self.active_calls
    
    def is_playing(self, chat_id: int) -> bool:
        """Проверить воспроизводится ли что-то в чате"""
        call_info = self.active_calls.get(chat_id)
        return bool(call_info and call_info.get('current_stream') and not call_info.get('is_paused'))
    
    def is_paused(self, chat_id: int) -> bool:
        """Проверить на паузе ли стрим"""
        call_info = self.active_calls.get(chat_id)
        return bool(call_info and call_info.get('is_paused'))
    
    async def cleanup(self):
        """Cleanup backend resources"""
        try:
            # Покидаем все активные чаты
            for chat_id in list(self.active_calls.keys()):
                await self.leave_voice_chat(chat_id)
            
            # Останавливаем PyTgCalls
            if self.pytgcalls:
                try:
                    # Современные версии используют stop()
                    if hasattr(self.pytgcalls, 'stop'):
                        await self.pytgcalls.stop()
                    logging.info("✅ PyTgCalls stopped")
                except Exception as e:
                    logging.error(f"❌ Error stopping PyTgCalls: {e}")
                finally:
                    self.pytgcalls = None
            
            # Останавливаем Pyrogram клиент
            if self.client:
                try:
                    await self.client.stop()
                    logging.info("✅ Pyrogram client stopped")
                except Exception as e:
                    logging.error(f"❌ Error stopping Pyrogram client: {e}")
                finally:
                    self.client = None
            
            self.is_initialized = False
            self.active_calls.clear()
            
        except Exception as e:
            logging.error(f"❌ Error during backend cleanup: {e}")


@loader.tds
class VoiceChatNativeMod(loader.Module):
    """🎵 Native Voice Chat module with Pyrogram + PyTgCalls backend"""
    
    strings = {
        "name": "VoiceChatNative",
        "streaming_unavailable": "❌ <b>Streaming not available</b>\\n<code>{}</code>\\n\\n<b>Required:</b> <code>pip install pyrogram py-tgcalls yt-dlp</code>",
        "not_configured": "❌ <b>Voice chat not configured</b>\\n\\nUse <code>.vcsetup</code> to configure Pyrogram session",
        "backend_failed": "❌ <b>Backend initialization failed</b>\\nCheck logs for details",
        "no_media": "❌ <b>No media found</b>\\nReply to media or provide YouTube URL",
        "unsupported_source": "❌ <b>Unsupported source</b>\\nSupported: YouTube, direct URLs, Telegram media",
        "download_failed": "❌ <b>Download failed</b>\\nCheck URL or try again later",
        "not_in_voice_chat": "❌ <b>Not in voice chat</b>\\nUse <code>.addm</code> or <code>.addv</code> first",
        "queue_empty": "❌ <b>Queue is empty</b>\\nAdd media with <code>.addm</code> or <code>.addv</code>",
        "vcsetup_start": "🔧 <b>Voice Chat Setup</b>\\n\\n1️⃣ Go to <a href='https://my.telegram.org/apps'>my.telegram.org/apps</a>\\n2️⃣ Create app and get API credentials\\n3️⃣ Send your API ID:",
        "vcsetup_api_hash": "✅ <b>API ID saved</b>\\n\\n4️⃣ Now send your API Hash:",
        "vcsetup_phone": "✅ <b>API Hash saved</b>\\n\\n5️⃣ Send your phone number with country code\\n<b>Example:</b> <code>+1234567890</code>",
        "vcsetup_code": "📱 <b>Authorization code sent</b>\\n\\n6️⃣ Enter the code from Telegram:",
        "vcsetup_2fa": "🔐 <b>2FA enabled</b>\\n\\n7️⃣ Enter your 2FA password:",
        "vcsetup_complete": "✅ <b>Voice chat configured successfully!</b>\\n\\nBackend: <b>Pyrogram + PyTgCalls</b>\\nStatus: <b>Ready</b>\\n\\nYou can now use: <code>.addm</code>, <code>.addv</code>, <code>.pause</code>, <code>.resume</code>, <code>.stop</code>",
        "vcsetup_failed": "❌ <b>Setup failed:</b> <code>{}</code>",
        "added_to_queue": "✅ <b>Added to queue</b>\\n\\n📂 <b>Title:</b> <code>{}</code>\\n⏱️ <b>Duration:</b> <code>{}s</code>\\n🔢 <b>Position:</b> <code>{}</code>",
        "playing_now": "🎵 <b>Now playing</b>\\n\\n📂 <b>Title:</b> <code>{}</code>\\n⏱️ <b>Duration:</b> <code>{}s</code>\\n📍 <b>Chat:</b> <code>{}</code>",
        "paused": "⏸️ <b>Paused</b>",
        "resumed": "▶️ <b>Resumed</b>", 
        "stopped": "⏹️ <b>Stopped and left voice chat</b>",
        "queue_status": "📋 <b>Queue ({} items)</b>\\n\\n{}",
        "queue_item": "{}. <b>{}</b> ({}s) {}\\n",
        "repeat_enabled": "🔁 <b>Repeat mode enabled</b>",
        "repeat_disabled": "🔁 <b>Repeat mode disabled</b>",
        "queue_cleared": "🗑️ <b>Queue cleared</b>",
    }
    
    
    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "auto_join",
                True,
                lambda: "Auto join voice chat when adding media",
                validator=loader.validators.Boolean
            ),
            loader.ConfigValue(
                "auto_play",
                True,
                lambda: "Auto start playing when queue is not empty",
                validator=loader.validators.Boolean
            ),
            loader.ConfigValue(
                "max_duration",
                3600,
                lambda: "Maximum media duration in seconds (0 = no limit)",
                validator=loader.validators.Integer
            ),
        )
        
        # Core components
        self.temp_manager = TempFileManager()
        self.queue_manager = None
        self.backend = None
        
        # Source resolvers
        self.youtube_resolver = None
        self.url_resolver = None
        self.telegram_resolver = None
        
        # State для vcsetup
        self.setup_states = {}
        self.temp_clients = {}
    
    async def client_ready(self):
        """Инициализация модуля"""
        # client и db доступны как self._client и self.db из loader.Module
        
        # Инициализируем менеджер очередей
        self.queue_manager = QueueManager(self.db)
        await self.queue_manager.load_queues()
        
        # Инициализируем resolvers
        self.youtube_resolver = YouTubeSourceResolver(self.temp_manager)
        self.url_resolver = DirectURLSourceResolver(self.temp_manager)
        self.telegram_resolver = TelegramMediaSourceResolver(self.temp_manager, self._client)
        
        # Проверяем настройки и инициализируем backend
        await self._initialize_backend()
    
    async def _initialize_backend(self):
        """Инициализация streaming backend"""
        try:
            # Получаем сохраненную сессию
            session_data = self.db.get("VoiceChatNative", "session", {})
            if not session_data or not session_data.get("session_string"):
                logging.info("❌ No Pyrogram session found")
                return
            
            api_id = session_data.get("api_id")
            api_hash = session_data.get("api_hash")
            session_string = session_data.get("session_string")
            
            if not all([api_id, api_hash, session_string]):
                logging.error("❌ Incomplete session data")
                return
            
            # Инициализируем backend
            self.backend = PyrogramTgCallsBackend()
            success = await self.backend.initialize(api_id, api_hash, session_string)
            
            if success:
                logging.info("✅ Voice chat backend initialized")
            else:
                logging.error("❌ Backend initialization failed")
                self.backend = None
                
        except Exception as e:
            logging.error(f"❌ Backend init error: {e}")
            self.backend = None
    
    async def on_unload(self):
        """Очистка при выгрузке модуля"""
        if hasattr(self, 'temp_manager'):
            self.temp_manager.cleanup_all()
        
        if hasattr(self, 'backend') and self.backend:
            await self.backend.cleanup()
        
        # Очистка temp clients от vcsetup
        for client in self.temp_clients.values():
            try:
                if client and client.is_connected:
                    await client.stop()
            except:
                pass
        self.temp_clients.clear()
    
    @loader.command()
    async def vcsetup(self, message):
        """Configure voice chat with Pyrogram session"""
        if not STREAMING_AVAILABLE:
            await utils.answer(message, self.strings["streaming_unavailable"].format(STREAMING_ERROR))
            return
        
        user_id = message.sender_id
        
        # Сброс предыдущего состояния если есть
        if user_id in self.setup_states:
            # Очищаем старый temp client
            old_client = self.temp_clients.get(user_id)
            if old_client:
                try:
                    await old_client.stop()
                except:
                    pass
                del self.temp_clients[user_id]
            
            del self.setup_states[user_id]
        
        # Начинаем новую настройку
        self.setup_states[user_id] = {"step": "api_id"}
        await utils.answer(message, self.strings["vcsetup_start"])
    
    async def watcher(self, message):
        """Watcher для обработки vcsetup steps"""
        if not message.sender_id or message.sender_id not in self.setup_states:
            return
        
        user_id = message.sender_id
        state = self.setup_states[user_id]
        
        try:
            if state["step"] == "api_id":
                # Получаем API ID
                try:
                    api_id = int(message.text.strip())
                    state["api_id"] = api_id
                    state["step"] = "api_hash"
                    await utils.answer(message, self.strings["vcsetup_api_hash"])
                except ValueError:
                    await utils.answer(message, "❌ <b>Invalid API ID</b>\\nSend numbers only")
                    return
            
            elif state["step"] == "api_hash":
                # Получаем API Hash
                api_hash = message.text.strip()
                state["api_hash"] = api_hash
                state["step"] = "phone"
                await utils.answer(message, self.strings["vcsetup_phone"])
            
            elif state["step"] == "phone":
                # Получаем номер телефона и отправляем код
                phone = message.text.strip()
                state["phone"] = phone
                
                try:
                    # Создаем временный Pyrogram клиент
                    temp_client = PyrogramClient(
                        f"temp_session_{user_id}",
                        api_id=state["api_id"],
                        api_hash=state["api_hash"],
                        no_updates=True
                    )
                    
                    await temp_client.connect()
                    sent_code = await temp_client.send_code(phone)
                    
                    state["phone_code_hash"] = sent_code.phone_code_hash
                    state["step"] = "code"
                    state["temp_client"] = temp_client
                    self.temp_clients[user_id] = temp_client
                    
                    await utils.answer(message, self.strings["vcsetup_code"])
                    
                except Exception as e:
                    await utils.answer(message, self.strings["vcsetup_failed"].format(str(e)))
                    del self.setup_states[user_id]
                    return
            
            elif state["step"] == "code":
                # Получаем код и авторизуемся
                code = message.text.strip()
                
                try:
                    temp_client = state["temp_client"]
                    
                    try:
                        signed_in = await temp_client.sign_in(
                            state["phone"],
                            state["phone_code_hash"],
                            code
                        )
                        
                        # Успешная авторизация - получаем session string
                        session_string = await temp_client.export_session_string()
                        
                        # Сохраняем в базу
                        session_data = {
                            "api_id": state["api_id"],
                            "api_hash": state["api_hash"],
                            "session_string": session_string,
                            "phone": state["phone"],
                            "created_at": time.time()
                        }
                        
                        self.db.set("VoiceChatNative", "session", session_data)
                        
                        # Инициализируем backend
                        await self._initialize_backend()
                        
                        await utils.answer(message, self.strings["vcsetup_complete"])
                        
                        # Очистка
                        await temp_client.stop()
                        del self.temp_clients[user_id]
                        del self.setup_states[user_id]
                        
                    except SessionPasswordNeeded:
                        # Требуется 2FA пароль
                        state["step"] = "2fa"
                        await utils.answer(message, self.strings["vcsetup_2fa"])
                        
                except Exception as e:
                    await utils.answer(message, self.strings["vcsetup_failed"].format(str(e)))
                    # Очистка при ошибке
                    temp_client = self.temp_clients.get(user_id)
                    if temp_client:
                        try:
                            await temp_client.stop()
                        except:
                            pass
                        del self.temp_clients[user_id]
                    del self.setup_states[user_id]
                    return
            
            elif state["step"] == "2fa":
                # Получаем 2FA пароль
                password = message.text.strip()
                
                try:
                    temp_client = state["temp_client"]
                    
                    # Авторизация с 2FA
                    await temp_client.check_password(password)
                    
                    # Получаем session string
                    session_string = await temp_client.export_session_string()
                    
                    # Сохраняем в базу
                    session_data = {
                        "api_id": state["api_id"],
                        "api_hash": state["api_hash"],
                        "session_string": session_string,
                        "phone": state["phone"],
                        "created_at": time.time()
                    }
                    
                    self.db.set("VoiceChatNative", "session", session_data)
                    
                    # Инициализируем backend
                    await self._initialize_backend()
                    
                    await utils.answer(message, self.strings["vcsetup_complete"])
                    
                    # Очистка
                    await temp_client.stop()
                    del self.temp_clients[user_id]
                    del self.setup_states[user_id]
                    
                except Exception as e:
                    await utils.answer(message, self.strings["vcsetup_failed"].format(str(e)))
                    # Очистка при ошибке
                    temp_client = self.temp_clients.get(user_id)
                    if temp_client:
                        try:
                            await temp_client.stop()
                        except:
                            pass
                        del self.temp_clients[user_id]
                    del self.setup_states[user_id]
                    return
                    
        except Exception as e:
            logging.error(f"❌ Watcher error: {e}")
            await utils.answer(message, self.strings["vcsetup_failed"].format(str(e)))
            # Очистка при любой ошибке
            if user_id in self.temp_clients:
                try:
                    await self.temp_clients[user_id].stop()
                except:
                    pass
                del self.temp_clients[user_id]
            if user_id in self.setup_states:
                del self.setup_states[user_id]
    
    @loader.command()
    async def addm(self, message):
        """Add music to voice chat queue"""
        if not await self._check_streaming_available(message):
            return
        
        if not await self._check_backend(message):
            return
        
        # Получаем источник медиа
        source = await self._get_media_source(message)
        if not source:
            await utils.answer(message, self.strings["no_media"])
            return
        
        # Обрабатываем источник
        queue_item = await self._resolve_source(source, {"user_id": message.sender_id, "is_video": False})
        if not queue_item:
            await utils.answer(message, self.strings["download_failed"])
            return
        
        # Добавляем в очередь
        chat_id = utils.get_chat_id(message)
        position = self.queue_manager.add_item(chat_id, queue_item)
        await self.queue_manager.save_queues()
        
        await utils.answer(
            message,
            self.strings["added_to_queue"].format(
                queue_item.title,
                queue_item.duration,
                position
            )
        )
        
        # Автозапуск если включен
        if self.config["auto_play"] and not self.backend.is_playing(chat_id):
            await self._play_next(chat_id)
    
    @loader.command()
    async def addv(self, message):
        """Add video to voice chat queue"""
        if not await self._check_streaming_available(message):
            return
        
        if not await self._check_backend(message):
            return
        
        # Получаем источник медиа
        source = await self._get_media_source(message)
        if not source:
            await utils.answer(message, self.strings["no_media"])
            return
        
        # Обрабатываем источник
        queue_item = await self._resolve_source(source, {"user_id": message.sender_id, "is_video": True})
        if not queue_item:
            await utils.answer(message, self.strings["download_failed"])
            return
        
        # Принудительно делаем видео
        queue_item.is_video = True
        
        # Добавляем в очередь
        chat_id = utils.get_chat_id(message)
        position = self.queue_manager.add_item(chat_id, queue_item)
        await self.queue_manager.save_queues()
        
        await utils.answer(
            message,
            self.strings["added_to_queue"].format(
                queue_item.title,
                queue_item.duration,
                position
            )
        )
        
        # Автозапуск если включен
        if self.config["auto_play"] and not self.backend.is_playing(chat_id):
            await self._play_next(chat_id)
    
    @loader.command()
    async def pause(self, message):
        """Pause current playback"""
        if not await self._check_backend(message):
            return
        
        chat_id = utils.get_chat_id(message)
        
        if not self.backend.is_playing(chat_id):
            await utils.answer(message, self.strings["not_in_voice_chat"])
            return
        
        success = await self.backend.pause_stream(chat_id)
        if success:
            await utils.answer(message, self.strings["paused"])
        else:
            await utils.answer(message, "❌ <b>Failed to pause</b>")
    
    @loader.command()
    async def resume(self, message):
        """Resume playback"""
        if not await self._check_backend(message):
            return
        
        chat_id = utils.get_chat_id(message)
        
        if not self.backend.is_paused(chat_id):
            await utils.answer(message, "❌ <b>Not paused</b>")
            return
        
        success = await self.backend.resume_stream(chat_id)
        if success:
            await utils.answer(message, self.strings["resumed"])
        else:
            await utils.answer(message, "❌ <b>Failed to resume</b>")
    
    @loader.command()
    async def stop(self, message):
        """Stop playback and leave voice chat"""
        if not await self._check_backend(message):
            return
        
        chat_id = utils.get_chat_id(message)
        
        if not self.backend.is_in_call(chat_id):
            await utils.answer(message, self.strings["not_in_voice_chat"])
            return
        
        success = await self.backend.stop_stream(chat_id)
        if success:
            # Очищаем очередь
            self.queue_manager.clear_queue(chat_id)
            await self.queue_manager.save_queues()
            await utils.answer(message, self.strings["stopped"])
        else:
            await utils.answer(message, "❌ <b>Failed to stop</b>")
    
    @loader.command()
    async def queue(self, message):
        """Show current queue"""
        chat_id = utils.get_chat_id(message)
        queue = self.queue_manager.get_queue(chat_id)
        
        if not queue:
            await utils.answer(message, self.strings["queue_empty"])
            return
        
        current_index = self.queue_manager._current_playing.get(chat_id, 0)
        
        queue_text = ""
        for i, item in enumerate(queue):
            marker = "▶️ " if i == current_index else ""
            queue_text += self.strings["queue_item"].format(
                i + 1,
                item.title,
                item.duration,
                marker
            )
        
        repeat_status = " 🔁" if self.queue_manager.is_repeat_enabled(chat_id) else ""
        
        await utils.answer(
            message,
            self.strings["queue_status"].format(len(queue), queue_text) + repeat_status
        )
    
    @loader.command()
    async def repeat(self, message):
        """Toggle repeat mode"""
        chat_id = utils.get_chat_id(message)
        current_repeat = self.queue_manager.is_repeat_enabled(chat_id)
        
        self.queue_manager.set_repeat(chat_id, not current_repeat)
        await self.queue_manager.save_queues()
        
        if not current_repeat:
            await utils.answer(message, self.strings["repeat_enabled"])
        else:
            await utils.answer(message, self.strings["repeat_disabled"])
    
    @loader.command()
    async def clearqueue(self, message):
        """Clear current queue"""
        chat_id = utils.get_chat_id(message)
        self.queue_manager.clear_queue(chat_id)
        await self.queue_manager.save_queues()
        
        await utils.answer(message, self.strings["queue_cleared"])
    
    # Helper methods
    
    async def _check_streaming_available(self, message) -> bool:
        """Проверка доступности стриминга"""
        if not STREAMING_AVAILABLE:
            await utils.answer(message, self.strings["streaming_unavailable"].format(STREAMING_ERROR))
            return False
        return True
    
    async def _check_backend(self, message) -> bool:
        """Проверка готовности backend"""
        if not self.backend or not self.backend.is_initialized:
            await utils.answer(message, self.strings["not_configured"])
            return False
        return True
    
    async def _get_media_source(self, message):
        """Получить источник медиа из сообщения"""
        # Проверяем аргументы команды
        args = utils.get_args_raw(message)
        if args:
            # Проверяем YouTube URL
            if "youtube.com" in args or "youtu.be" in args:
                return {"type": "youtube", "url": args}
            # Проверяем прямой URL
            elif args.startswith(("http://", "https://")):
                return {"type": "url", "url": args}
        
        # Проверяем reply медиа
        reply = await message.get_reply_message()
        if reply and reply.media:
            return {"type": "telegram", "message": reply}
        
        return None
    
    async def _resolve_source(self, source, metadata):
        """Обработка источника медиа"""
        try:
            if source["type"] == "youtube":
                return await self.youtube_resolver.resolve(source["url"], metadata)
            elif source["type"] == "url":
                return await self.url_resolver.resolve(source["url"], metadata)
            elif source["type"] == "telegram":
                return await self.telegram_resolver.resolve(source["message"], metadata)
        except Exception as e:
            logging.error(f"❌ Source resolve error: {e}")
            return None
    
    async def _play_next(self, chat_id: int):
        """Воспроизвести следующий элемент из очереди"""
        try:
            current_item = self.queue_manager.get_current(chat_id)
            if not current_item:
                return
            
            # Проверяем файл
            if not os.path.exists(current_item.file_path):
                logging.error(f"❌ File not found: {current_item.file_path}")
                # Переходим к следующему
                next_item = self.queue_manager.next_item(chat_id)
                if next_item:
                    await self._play_next(chat_id)
                return
            
            # Воспроизводим
            success = await self.backend.play_media(
                chat_id, 
                current_item.file_path, 
                current_item.is_video
            )
            
            if success:
                # Отправляем уведомление если возможно
                chat_title = f"Chat {chat_id}"  # Можно получить через self.client
                logging.info(f"🎵 Now playing: {current_item.title} in {chat_title}")
            else:
                logging.error(f"❌ Failed to play: {current_item.title}")
                # Пробуем следующий
                next_item = self.queue_manager.next_item(chat_id)
                if next_item:
                    await self._play_next(chat_id)
                    
        except Exception as e:
            logging.error(f"❌ Play next error: {e}")