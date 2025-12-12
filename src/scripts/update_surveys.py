import asyncio
import sys
import json
from os.path import abspath, dirname

sys.path.insert(0, dirname(dirname(dirname(abspath(__file__)))))

from src.services.redis import redis_service
from src.config import settings
from src.services.sheets import fetch_all_data

async def update_surveys():
    print("🌍 Скачиваю данные из Google Sheets...")
    try:
        surveys, prompts = await fetch_all_data()
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return

    
    
    # 1. Сохраняем анкеты
    for mode, questions in surveys.items():
        await redis_service.set_survey_config(mode, questions)
        print(f"✅ Анкета {mode}: {len(questions)} вопросов")

    for mode, text in prompts.items():
        await redis_service.set_prompt(mode, text) # <--- ИЗМЕНЕНИЕ
        print(f"✅ Промпт {mode} обновлен")
    
    

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(update_surveys())