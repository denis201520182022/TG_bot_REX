import httpx
from openai import AsyncOpenAI
from src.config import settings

# Формируем URL прокси
PROXY_URL = (
    f"http://{settings.SQUID_PROXY_USER}:{settings.SQUID_PROXY_PASSWORD}@"
    f"{settings.SQUID_PROXY_HOST}:{settings.SQUID_PROXY_PORT}"
)

# Создаем http клиент один раз (глобально), чтобы переиспользовать соединения
http_client = httpx.AsyncClient(
    proxy=PROXY_URL,
    timeout=60.0
)

# Клиент OpenAI
client = AsyncOpenAI(
    api_key=settings.OPENAI_API_KEY.get_secret_value(),
    http_client=http_client
)

async def generate_response(system_prompt: str, user_content: str) -> str:
    """
    Универсальная функция генерации (OpenAI / Qwen Compatible)
    """
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini", # Или gpt-3.5-turbo, пока тестим. Потом заменим на qwen-max
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.7,
            max_tokens=1500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка генерации LLM: {str(e)}"