import aiohttp
import json
from src.config import settings

# URL для Qwen (проверь в документации Alibaba, обычно такой для совместимого API)
# Если используешь библиотеку dashscope, можно переписать через неё.
# Но через REST API надежнее для asyncio.
QWEN_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

async def generate_response(system_prompt: str, user_data: str) -> str:
    """
    Отправляет запрос к Qwen3-Max
    """
    headers = {
        "Authorization": f"Bearer {settings.QWEN_API_KEY.get_secret_value()}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "qwen-max", # Или qwen-plus / qwen-turbo
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_data}
        ],
        "temperature": 0.7
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(QWEN_URL, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Qwen Compatible API format
                    return data['choices'][0]['message']['content']
                else:
                    error_text = await resp.text()
                    return f"Ошибка API ({resp.status}): {error_text}"
        except Exception as e:
            return f"Ошибка соединения: {str(e)}"