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

async def process_notification(message: aio_pika.IncomingMessage, bot: Bot):
    try:
        data = json.loads(message.body)
        user_id = data['user_id']
        text = data.get('text', '')
        photo = data.get('photo')
        
        # Десериализуем клавиатуру из JSON обратно в объект aiogram
        keyboard_data = data.get('keyboard')
        keyboard = InlineKeyboardMarkup.model_validate(keyboard_data) if keyboard_data else None

        print(f"📨 [Sender] Отправка для {user_id}...")

        # --- ОТПРАВКА ---
        if photo:
            await bot.send_photo(chat_id=user_id, photo=photo, caption=text, reply_markup=keyboard)
        else:
            await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)

        # Подтверждаем, что сообщение обработано успешно
        await message.ack()

    except TelegramRetryAfter as e:
        print(f"⏳ Лимит Telegram. Ждем {e.retry_after} сек. Возвращаю задачу в очередь.")
        # Возвращаем в очередь, чтобы попробовать позже
        await message.nack(requeue=True)
        # Можно добавить небольшую паузу перед тем, как воркер возьмет новую задачу
        await asyncio.sleep(e.retry_after) 

    except Exception as e:
        print(f"❌ Критическая ошибка отправки: {e}. Удаляю задачу из очереди.")
        # Если ошибка не связана с лимитом (например, user_id невалидный), 
        # удаляем сообщение, чтобы не зацикливать очередь
        await message.ack()

async def main():
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
    
    print("📨 Sender Worker запущен и ждет писем...")
    
    # Настраиваем QoS (Quality of Service)
    # Берем по 10 сообщений за раз, чтобы асинхронно их раскидывать
    await channel.set_qos(prefetch_count=10)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            # Запускаем отправку в фоне, не блокируя цикл
            asyncio.create_task(process_notification(message, bot))

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())