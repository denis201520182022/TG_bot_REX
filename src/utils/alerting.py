import traceback
import httpx
from src.config import settings
from src.utils.logger import logger

async def send_alert(error: Exception, context: str = "System"):
    """
    Отправляет сообщение об ошибке администратору напрямую через HTTP API Telegram.
    (Минуя RabbitMQ, чтобы работало даже если очереди упали).
    """
    admin_ids = settings.ADMIN_IDS.split(',')
    token = settings.BOT_TOKEN.get_secret_value()
    
    error_trace = traceback.format_exc()
    short_error = str(error)[:1000] # Обрезаем, чтобы влезло
    
    text = (
        f"🚨 <b>CRITICAL ERROR in {context}</b>\n\n"
        f"Error: <code>{short_error}</code>\n\n"
        f"Traceback:\n<pre>{error_trace[-1000:]}</pre>" # Последние 1000 символов трейса
    )

    async with httpx.AsyncClient() as client:
        for admin_id in admin_ids:
            try:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                await client.post(url, json={
                    "chat_id": admin_id,
                    "text": text,
                    "parse_mode": "HTML"
                })
            except Exception as e:
                logger.error("failed_to_send_alert", error=str(e))