import asyncio
import json
import sys
import aio_pika
from os.path import abspath, dirname
from aiogram.types import InlineKeyboardMarkup

# Магия путей
sys.path.insert(0, dirname(dirname(dirname(abspath(__file__)))))

from src.config import settings
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter

# --- OBSERVABILITY (Логи, Метрики, Алерты) ---
from src.utils.logger import logger
from src.utils.metrics import start_metrics_server, MESSAGES_SENT, SYSTEM_ERRORS
from src.utils.alerting import send_alert

async def process_notification(message: aio_pika.IncomingMessage, bot: Bot):
    try:
        data = json.loads(message.body)
        user_id = data['user_id']
        text = data.get('text', '')
        photo = data.get('photo')
        
        # Десериализуем клавиатуру из JSON обратно в объект aiogram
        keyboard_data = data.get('keyboard')
        keyboard = InlineKeyboardMarkup.model_validate(keyboard_data) if keyboard_data else None

        # Структурный логгер с контекстом
        log = logger.bind(user_id=user_id, worker="sender")
        log.info("sending_message_attempt")

        # --- ОТПРАВКА ---
        if photo:
            await bot.send_photo(chat_id=user_id, photo=photo, caption=text, reply_markup=keyboard)
        else:
            await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)

        # Метрика успеха
        MESSAGES_SENT.labels(status="success").inc()
        log.info("message_sent_successfully")

        # Подтверждаем, что сообщение обработано успешно
        await message.ack()

    except TelegramRetryAfter as e:
        # Метрика лимитов
        MESSAGES_SENT.labels(status="rate_limit").inc()
        
        # Логируем как warning, это штатная ситуация для HighLoad
        logger.warning("telegram_rate_limit", retry_after=e.retry_after, user_id=user_id)
        
        # Возвращаем в очередь, чтобы попробовать позже
        await message.nack(requeue=True)
        # Можно добавить небольшую паузу перед тем, как воркер возьмет новую задачу
        await asyncio.sleep(e.retry_after) 

    except Exception as e:
        # Метрика ошибки
        MESSAGES_SENT.labels(status="failed").inc()
        SYSTEM_ERRORS.labels(service="sender", error_type=type(e).__name__).inc()
        
        # Логируем ошибку
        logger.error("sending_failed_critical", error=str(e), user_id=user_id)
        
        # Критический алерт админу
        await send_alert(e, context="Sender Worker")
        
        # Если ошибка не связана с лимитом (например, user_id невалидный), 
        # удаляем сообщение, чтобы не зацикливать очередь
        await message.ack()

async def main():
    logger.info("service_started", service="sender")
    
    # Инициализация бота
    bot = Bot(
        token=settings.BOT_TOKEN.get_secret_value(), 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    # Подключение к RabbitMQ
    connection = await aio_pika.connect_robust(settings.RABBIT_URL)
    channel = await connection.channel()
    
    # Очередь уведомлений
    queue = await channel.declare_queue("q_notifications", durable=True)
    
    # Настраиваем QoS (Quality of Service)
    await channel.set_qos(prefetch_count=10)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            # Запускаем отправку в фоне, не блокируя цикл
            asyncio.create_task(process_notification(message, bot))

if __name__ == "__main__":
    # Запуск сервера метрик на порту 8001
    start_metrics_server(8001)
    
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("service_stopped")