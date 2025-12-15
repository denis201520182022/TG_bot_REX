import httpx
import time
from openai import AsyncOpenAI
from prometheus_client import Histogram
from src.config import settings

# --- OBSERVABILITY ---
from src.utils.logger import logger
from src.utils.alerting import send_alert
from src.utils.metrics import SYSTEM_ERRORS

# Метрика времени ответа
LLM_API_DURATION = Histogram(
    'rex_llm_api_request_duration_seconds',
    'Time spent waiting for LLM response'
)

# HTTP клиент
http_client = httpx.AsyncClient(timeout=60.0)

# Клиент Groq (через OpenAI интерфейс)
client = AsyncOpenAI(
    api_key=settings.OPENAI_API_KEY.get_secret_value(),
    base_url="https://api.groq.com/openai/v1",
    http_client=http_client
)

async def generate_response(system_prompt: str, user_content: str) -> str:
    """
    Генерация ответа через Groq (Llama-3.3).
    """
    start_time = time.time()
    
    # Очень быстрая и мощная модель
    MODEL_NAME = "llama-3.3-70b-versatile" 

    log = logger.bind(service="llm_client", provider="groq", model=MODEL_NAME)

    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.7,
            max_tokens=1500,
            stream=False
        )
        
        duration = time.time() - start_time
        LLM_API_DURATION.observe(duration)
        
        return response.choices[0].message.content

    except Exception as e:
        duration = time.time() - start_time
        error_msg = str(e)
        
        log.error("llm_request_failed", error=error_msg, duration=duration)
        SYSTEM_ERRORS.labels(service="llm", error_type=type(e).__name__).inc()
        await send_alert(e, context=f"LLM Service ({MODEL_NAME})")
        
        raise e