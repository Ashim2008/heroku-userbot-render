# ------------------------------------------------------------
# Module: LogSettings
# Description: Manage logging settings and filters 
# Author: Heroku Userbot
# ------------------------------------------------------------
# Licensed under the GNU AGPLv3
# https://www.gnu.org/licenses/agpl-3.0.html
# ------------------------------------------------------------
# Commands: .connectionspam .logfilters
# ------------------------------------------------------------

from .. import loader, utils

@loader.tds
class LogSettingsMod(loader.Module):
    """Manage logging settings and filters"""
    strings = {
        "name": "LogSettings",
        "connection_spam_enabled": "<emoji document_id=5472146462362048818>✅</emoji> <b>Connection error messages enabled</b>\n\n<i>Now you will see messages about internet connection problems in logs.</i>",
        "connection_spam_disabled": "<emoji document_id=5465300982628759216>❌</emoji> <b>Connection error messages disabled</b>\n\n<i>Connection error messages are now hidden from logs.</i>",
        "current_settings": "<emoji document_id=5472308992514464048>⚙️</emoji> <b>Current log filter settings:</b>\n\n<emoji document_id=5463280316042533202>📡</emoji> <b>Connection error messages:</b> <code>{}</code>\n<emoji document_id=5469741319330996757>📊</emoji> <b>Failed updates filter:</b> <code>enabled</code>",
        "settings_help": "<emoji document_id=5472308992514464048>⚙️</emoji> <b>Log Settings Help</b>\n\n<b>Available commands:</b>\n<code>.connectionspam</code> - Toggle connection error messages\n<code>.logfilters</code> - View current filter settings\n\n<b>Filters:</b>\n• <b>Connection Spam Filter</b> - Hides annoying connection error messages\n• <b>Update Fetch Filter</b> - Hides 'Failed to fetch updates' messages"
    }

    strings_ru = {
        "name": "LogSettings", 
        "connection_spam_enabled": "<emoji document_id=5472146462362048818>✅</emoji> <b>Сообщения об ошибках соединения включены</b>\n\n<i>Теперь вы будете видеть сообщения о проблемах с интернет-соединением в логах.</i>",
        "connection_spam_disabled": "<emoji document_id=5465300982628759216>❌</emoji> <b>Сообщения об ошибках соединения отключены</b>\n\n<i>Сообщения об ошибках соединения скрыты из логов.</i>",
        "current_settings": "<emoji document_id=5472308992514464048>⚙️</emoji> <b>Текущие настройки фильтров логов:</b>\n\n<emoji document_id=5463280316042533202>📡</emoji> <b>Сообщения об ошибках соединения:</b> <code>{}</code>\n<emoji document_id=5469741319330996757>📊</emoji> <b>Фильтр неудачных обновлений:</b> <code>включен</code>",
        "settings_help": "<emoji document_id=5472308992514464048>⚙️</emoji> <b>Помощь по настройкам логов</b>\n\n<b>Доступные команды:</b>\n<code>.connectionspam</code> - Переключить сообщения об ошибках соединения\n<code>.logfilters</code> - Посмотреть текущие настройки фильтров\n\n<b>Фильтры:</b>\n• <b>Фильтр спама соединения</b> - Скрывает надоедливые сообщения об ошибках соединения\n• <b>Фильтр обновлений</b> - Скрывает сообщения 'Failed to fetch updates'"
    }

    def __init__(self):
        self.name = self.strings["name"]

    async def client_ready(self):
        # Устанавливаем значения по умолчанию
        if self.db.get(self.__class__.__name__, "connection_spam_disabled") is None:
            self.db.set(self.__class__.__name__, "connection_spam_disabled", True)  # По умолчанию отключено

    def is_connection_spam_disabled(self) -> bool:
        """Check if connection spam messages are disabled"""
        return self.db.get(self.__class__.__name__, "connection_spam_disabled", True)

    @loader.command(
        ru_doc="Переключить показ сообщений об ошибках соединения в логах",
        en_doc="Toggle connection error messages in logs"
    )
    async def connectionspam(self, message):
        """Toggle connection error messages in logs"""
        current_state = self.is_connection_spam_disabled()
        new_state = not current_state
        
        self.db.set(self.__class__.__name__, "connection_spam_disabled", new_state)
        
        # Обновляем глобальную переменную для log.py
        import heroku.log as log_module
        log_module._connection_spam_disabled = new_state
        
        if new_state:
            await utils.answer(message, self.strings["connection_spam_disabled"])
        else:
            await utils.answer(message, self.strings["connection_spam_enabled"])

    @loader.command(
        ru_doc="Показать текущие настройки фильтров логов",
        en_doc="Show current log filter settings"
    )
    async def logfilters(self, message):
        """Show current log filter settings"""
        connection_spam_disabled = self.is_connection_spam_disabled()
        connection_status = "отключены" if connection_spam_disabled else "включены"
        
        await utils.answer(
            message, 
            self.strings["current_settings"].format(connection_status)
        )

    @loader.command(
        ru_doc="Помощь по настройкам логирования",
        en_doc="Help for logging settings"
    )
    async def loghelp(self, message):
        """Help for logging settings"""
        await utils.answer(message, self.strings["settings_help"])