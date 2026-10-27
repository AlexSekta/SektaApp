import logging
import os
import threading

from logging.handlers import RotatingFileHandler


# Корневая папка проекта WB_Analytics
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Папка логов
LOG_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(
    LOG_DIR,
    exist_ok=True,
)

# Главный лог приложения
LOG_FILE = os.path.join(LOG_DIR, "app.log")


class WindowsSafeRotatingFileHandler(RotatingFileHandler):
    """Keep logging if Windows temporarily locks the file during rotation."""

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            # Another process (or a log viewer) may be holding the file.
            # Keep appending to the current file and retry rotation later.
            if self.stream is None:
                self.stream = self._open()


_handler_lock = threading.RLock()
_shared_file_handler = None


def _file_handler():
    global _shared_file_handler
    if _shared_file_handler is None:
        handler = WindowsSafeRotatingFileHandler(
            LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        ))
        _shared_file_handler = handler
    return _shared_file_handler


class RussianConsoleFormatter(logging.Formatter):
    """
    Русифицирует сообщения приложения только в консоли.

    Технические коды событий остаются в logs/app.log.
    """

    EVENT_NAMES = {
        "BACKEND_START": "Запуск backend",
        "BACKEND_STOP": "Остановка backend",

        "AUTH_REGISTER": "Регистрация пользователя",
        "AUTH_LOGIN_FAILED": "Ошибка входа в систему",
        "AUTH_LOGIN_OK": "Успешный вход в систему",
        "PASSWORD_RESET_EMAIL_CONFIG_ERROR": "Ошибка настройки письма для восстановления пароля",
        "PASSWORD_RESET_REQUEST": "Запрос восстановления пароля",
        "PASSWORD_RESET_EMAIL_FAILED": "Не удалось отправить письмо для восстановления пароля",
        "PASSWORD_RESET_OK": "Пароль восстановлен",
        "PASSWORD_CHANGE_OK": "Пароль изменён",

        "PRODUCT_CREATE_FAILED": "Не удалось создать товар",
        "PRODUCT_UPDATE_FAILED": "Не удалось обновить товар",
        "PRODUCT_DELETE_FAILED": "Не удалось удалить товар",

        "1C_SYNC_FAILED": "Ошибка синхронизации 1С",
        "1C_IMPORT_START": "Начало импорта из 1С",
        "1C_FILE_VALIDATED": "Файл 1С проверен",
        "1C_IMPORT_OK": "Импорт из 1С завершён",
        "1C_IMPORT_FAILED": "Ошибка импорта из 1С",
        "1C_FILES_DELETE_FAILED": "Не удалось удалить файлы 1С",

        "STOCK_UPDATE_START": "Начало обновления остатков",
        "STOCK_UPDATE_OK": "Остатки успешно обновлены",
        "STOCK_UPDATE_ACCEPTED": "Обновление остатков принято",
        "STOCK_UPDATE_SKIPPED": "Обновление остатков пропущено",
        "STOCK_UPDATE_REJECTED": "Обновление остатков отклонено",
        "STOCK_UPDATE_FAILED": "Ошибка обновления остатков",
        "STOCK_UPDATE_DB_FAILED": "Ошибка базы данных при обновлении остатков",
        "STOCK_UPDATE_VERIFY_FAILED": "Ошибка проверки обновлённых остатков",

        "TENANT_BOOTSTRAP_ORGANIZATION": "Создана основная организация",
        "TENANT_SCHEMA_READY": "Схема базы данных готова",

        "WB_PRODUCT_SYNC_START": "Начало синхронизации товаров WB",
        "WB_PRODUCT_SYNC_OK": "Синхронизация товаров WB завершена",
        "WB_PRODUCT_SYNC_FAILED": "Ошибка синхронизации товаров WB",

        "WB_STOCK_SYNC_START": "Начало синхронизации остатков WB",
        "WB_STOCK_SYNC_OK": "Синхронизация остатков WB завершена",
        "WB_STOCK_SYNC_FAILED": "Ошибка синхронизации остатков WB",

        "WB_WAREHOUSE_SYNC_START": "Начало синхронизации складов WB",
        "WB_WAREHOUSE_SYNC_OK": "Синхронизация складов WB завершена",
        "WB_WAREHOUSE_SYNC_FAILED": "Ошибка синхронизации складов WB",

        "WB_QUESTIONS_SCHEDULER_STARTED": "Запущена автосинхронизация вопросов WB",
        "WB_QUESTIONS_SYNC_OK": "Синхронизация вопросов WB завершена",
        "WB_QUESTIONS_AUTO_SYNC_OK": "Автосинхронизация вопросов WB завершена",
        "WB_QUESTIONS_AUTO_SYNC_FAILED": "Ошибка автосинхронизации вопросов WB",

        "WB_REVIEWS_SCHEDULER_STARTED": "Запущена автосинхронизация отзывов WB",
        "WB_REVIEWS_SYNC_OK": "Синхронизация отзывов WB завершена",
        "WB_REVIEWS_AUTO_SYNC_OK": "Автосинхронизация отзывов WB завершена",
        "WB_REVIEWS_AUTO_SYNC_FAILED": "Ошибка автосинхронизации отзывов WB",

        "WB_REVIEW_RESPONSE_MONITOR_STARTED": "Запущен мониторинг ответов на отзывы WB",
        "WB_REVIEW_RESPONSE_MONITOR_BASELINE": "Создан исходный снимок очереди отзывов WB",
        "WB_REVIEW_RESPONSE_MONITOR_OK": "Мониторинг ответов на отзывы WB выполнен",
        "WB_REVIEW_RESPONSE_MONITOR_RUN": "Цикл мониторинга отзывов WB завершён",
        "WB_REVIEW_RESPONSE_MONITOR_FAILED": "Ошибка мониторинга ответов на отзывы WB",
        "WB_REVIEW_RESPONSE_MONITOR_SKIPPED_NO_ORGANIZATION": "Мониторинг отзывов WB пропущен: организация не определена",

        "WB_QUESTION_RESPONSE_MONITOR_STARTED": "Запущен мониторинг ответов на вопросы WB",
        "WB_QUESTION_RESPONSE_MONITOR_BASELINE": "Создан исходный снимок очереди вопросов WB",
        "WB_QUESTION_RESPONSE_MONITOR_OK": "Мониторинг ответов на вопросы WB выполнен",
        "WB_QUESTION_RESPONSE_MONITOR_RUN": "Цикл мониторинга вопросов WB завершён",
        "WB_QUESTION_RESPONSE_MONITOR_FAILED": "Ошибка мониторинга ответов на вопросы WB",
        "WB_QUESTION_RESPONSE_MONITOR_SKIPPED_NO_ORGANIZATION": "Мониторинг вопросов WB пропущен: организация не определена",

        "YANDEX_QUESTIONS_SCHEDULER_STARTED": "Запущена автосинхронизация вопросов Яндекс Маркета",
        "YANDEX_QUESTIONS_SCHEDULER_STOPPED": "Автосинхронизация вопросов Яндекс Маркета остановлена",
        "YANDEX_QUESTIONS_AUTO_SYNC_OK": "Автосинхронизация вопросов Яндекс Маркета завершена",
        "YANDEX_QUESTIONS_AUTO_SYNC_API_ERROR": "Ошибка API при синхронизации вопросов Яндекс Маркета",
        "YANDEX_QUESTIONS_AUTO_SYNC_ERROR": "Ошибка автосинхронизации вопросов Яндекс Маркета",

        "YANDEX_REVIEWS_SCHEDULER_STARTED": "Запущена автосинхронизация отзывов Яндекс Маркета",
        "YANDEX_REVIEWS_SYNC_OK": "Синхронизация отзывов Яндекс Маркета завершена",
        "YANDEX_REVIEWS_AUTO_SYNC_OK": "Автосинхронизация отзывов Яндекс Маркета завершена",
        "YANDEX_REVIEWS_AUTO_SYNC_FAILED": "Ошибка автосинхронизации отзывов Яндекс Маркета",

        "OZON_FBS_SYNC_OK": "Синхронизация FBS-остатков Ozon завершена",
        "OZON_FBO_SYNC_OK": "Синхронизация FBO-остатков Ozon завершена",

        "OZON_SALES_SCHEDULER_STARTED": "Запущена синхронизация продаж Ozon",
        "OZON_SALES_SYNC_OK": "Синхронизация продаж Ozon завершена",
        "OZON_SALES_AUTO_SYNC_OK": "Автосинхронизация продаж Ozon завершена",
        "OZON_SALES_AUTO_SYNC_FAILED": "Ошибка автосинхронизации продаж Ozon",
        "OZON_SALES_AUTO_SYNC_SKIPPED": "Автосинхронизация продаж Ozon пропущена",

        "SYNC_START": "Начало синхронизации",
        "SYNC_SKIPPED_NO_ORGANIZATION": "Синхронизация пропущена: организация не определена",
        "WB_SYNC_OK": "Синхронизация WB завершена",
        "STOCK_SYNC_START": "Начало общей синхронизации остатков",
        "STOCK_SYNC_FINISH": "Общая синхронизация остатков завершена",
        "SYNC_FINISH": "Синхронизация завершена",
        "SYNC_FAILED": "Ошибка синхронизации",
    }

    def format(self, record):
        # В предыдущей версии здесь была ошибка:
        # проверялось начало ВСЕЙ строки, а там уже стоят
        # timestamp | level | logger. Поэтому перевод никогда не срабатывал.
        message = record.getMessage()

        translated = None
        for event, text in self.EVENT_NAMES.items():
            if message.startswith(event):
                translated = text + message[len(event):]
                break

        if translated is None:
            translated = message

        # Формируем строку в том же формате, что и обычный formatter.
        result = (
            f"{self.formatTime(record, self.datefmt)} | "
            f"{record.levelname} | {record.name} | {translated}"
        )

        if record.exc_info:
            result += "\n" + self.formatException(record.exc_info)

        if record.stack_info:
            result += "\n" + self.formatStack(record.stack_info)

        return result

def get_logger(
    name: str = "marketplace_app",
):
    # Every named logger uses the *same* file handler in this process.
    # Separate handlers on one app.log prevent rotation on Windows.
    with _handler_lock:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if logger.handlers:
            return logger

        logger.addHandler(_file_handler())

        # Preserve per-logger Russian terminal output; file records remain
        # the unmodified technical event strings.
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            RussianConsoleFormatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
            )
        )
        logger.addHandler(console_handler)
        logger.propagate = False
        return logger
