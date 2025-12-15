import datetime
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from sqlalchemy import select

from src.database.session import async_session_maker
from src.database.models import User
from src.config import settings

class CheckSubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        
        # 1. Определяем user_id и тип события
        user = None
        if isinstance(event, Message):
            user = event.from_user
            # Исключение: Команду /start пускаем всегда, чтобы можно было ввести новый QR
            if event.text and event.text.startswith("/start"):
                return await handler(event, data)
                
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        
        if not user:
            return await handler(event, data)

        # 2. Исключение для Админов
        admin_ids = [int(x) for x in settings.ADMIN_IDS.split(',')]
        if user.id in admin_ids:
            return await handler(event, data)

        # 3. Проверка в Базе Данных
        async with async_session_maker() as session:
            db_user = await session.get(User, user.id)
            
            # Если юзера нет или подписка истекла
            if not db_user or not db_user.subscription_expires_at:
                return await self.send_block_message(event)
            
            # Сравниваем даты (с учетом часового пояса UTC)
            now = datetime.datetime.now(datetime.timezone.utc)
            
            if db_user.subscription_expires_at < now:
                return await self.send_block_message(event)

        # 4. Если все ок — пропускаем дальше
        return await handler(event, data)

    async def send_block_message(self, event: TelegramObject):
        """Отправляет сообщение о блокировке."""
        text = (
            "⛔️ <b>Ваш доступ истек.</b>\n\n"
            "Чтобы продолжить пользоваться Диетологом, Тренером и другими функциями, "
            "пожалуйста, отсканируйте <b>новый QR-код</b> с упаковки продукции REX."
        )
        
        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer("⛔️ Доступ истек. Отсканируйте новый код.", show_alert=True)
            # Опционально: можно удалить меню, чтобы не мозолило глаза
            await event.message.delete()