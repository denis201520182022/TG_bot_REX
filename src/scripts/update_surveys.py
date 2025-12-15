import asyncio
import sys
import json
from os.path import abspath, dirname

# Магия путей
sys.path.insert(0, dirname(dirname(dirname(abspath(__file__)))))

from src.services.redis import redis_service
from src.config import settings
from src.services.sheets import fetch_all_data

# --- OBSERVABILITY ---
from src.utils.logger import logger
from src.utils.alerting import send_alert

async def update_surveys():
    # Создаем контекстный логгер
    log = logger.bind(task="update_surveys", worker="script")
    log.info("google_sync_started")

    try:
        # Скачиваем данные
        surveys, prompts = await fetch_all_data()
    except Exception as e:
        # Логируем ошибку
        log.error("google_sync_failed", error=str(e))
        
        # Отправляем алерт админу
        await send_alert(e, context="Google Sheets Sync Script")
        
        # Пробрасываем ошибку наверх, чтобы Scheduler (если он вызвал) 
        # тоже зафиксировал сбой в метриках
        raise e

    # 1. Сохраняем анкеты
    count_surveys = 0
    for mode, questions in surveys.items():
        await redis_service.set_survey_config(mode, questions)
        count_surveys += 1
    
    # 2. Сохраняем промпты
    count_prompts = 0
    for mode, text in prompts.items():
        await redis_service.set_prompt(mode, text)
        count_prompts += 1
    
    log.info(
        "google_sync_completed", 
        surveys_updated=count_surveys, 
        prompts_updated=count_prompts,
        modes=list(surveys.keys())
    )

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(update_surveys())
    except Exception as e:
        # Если запускаем руками и скрипт упал - логируем фатал
        # (Логгер уже настроен внутри send_alert/logger импортов)
        logger.critical("script_execution_failed", error=str(e))
        sys.exit(1)