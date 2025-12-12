import json
from typing import Optional, Any
from redis.asyncio import Redis, from_url
from src.config import settings

# --- ЕДИНСТВЕННЫЙ ЭКЗЕМПЛЯР КЛИЕНТА ---
# Создаем один клиент Redis, который будет переиспользоваться во всем приложении
redis_client: Redis = from_url(settings.REDIS_URL, decode_responses=True)


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (Обертки) ---

class RedisService:
    """
    Класс-сервис для инкапсуляции всей логики работы с Redis.
    """
    def __init__(self, client: Redis):
        self.client = client

    # --- Работа с анкетами ---
    async def get_survey_config(self, mode: str) -> Optional[dict]:
        """Получает и декодирует JSON анкеты."""
        data = await self.client.get(f"survey_config:{mode}")
        return json.loads(data) if data else None

    async def set_survey_config(self, mode: str, config: dict):
        """Сохраняет JSON анкеты."""
        await self.client.set(f"survey_config:{mode}", json.dumps(config))

    # --- Работа с промптами ---
    async def get_prompt(self, mode: str) -> Optional[str]:
        """Получает текст промпта."""
        return await self.client.get(f"prompt:{mode}")
        
    async def set_prompt(self, mode: str, text: str):
        """Сохраняет текст промпта."""
        await self.client.set(f"prompt:{mode}", text)

    # --- Работа с гороскопами ---
    async def get_horoscope(self, sign: str) -> Optional[str]:
        """Получает гороскоп для знака."""
        return await self.client.get(f"horoscope:{sign}")

    async def set_horoscope(self, sign: str, text: str):
        """Сохраняет гороскоп для знака с TTL 24 часа."""
        await self.client.set(f"horoscope:{sign}", text, ex=86400) # ex = expire in seconds

    # --- Общие операции (если понадобятся) ---
    async def get(self, key: str) -> Optional[str]:
        return await self.client.get(key)

    async def set(self, key: str, value: Any, ex: int = None):
        await self.client.set(key, value, ex=ex)


# --- ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР СЕРВИСА ---
# Его мы будем импортировать в других частях кода
redis_service = RedisService(redis_client)