import sys
import structlog
import logging

def setup_logger():
    # Настраиваем стандартный logging, чтобы перехватывать логи библиотек
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars, # Добавляет контекст (user_id)
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer() # Вывод в JSON
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger()

# Глобальный логгер
logger = setup_logger()