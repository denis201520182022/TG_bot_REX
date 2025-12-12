import asyncio
import logging
import sys
import datetime
from os.path import abspath, dirname

# Пути
sys.path.insert(0, dirname(dirname(dirname(abspath(__file__)))))

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import structlog

from src.config import settings
from src.database.session import async_session_maker
from src.database.models import User, QRCode
from sqlalchemy import select
from src.services.redis import redis_client

# ИМПОРТЫ РОУТЕРОВ
from src.bot.keyboards.menu import get_main_menu
from src.bot.handlers import survey as survey_router
from src.bot.handlers import dating as dating_router
from src.bot.handlers import tracking as tracking_router
from src.bot.handlers import profile as profile_router 

structlog.configure(processors=[structlog.processors.JSONRenderer()])
logger = structlog.get_logger()

async def start_handler(message: Message, command: CommandObject):
    args = command.args # То, что после /start
    user_id = message.from_user.id
    
    async with async_session_maker() as session:
        # 1. Проверяем или создаем юзера
        stmt = select(User).where(User.user_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                user_id=user_id,
                username=message.from_user.username,
                full_name=message.from_user.full_name
            )
            session.add(user)
            await session.commit()
            logger.info("new_user_registered", user_id=user_id)

        # 2. Если есть аргумент (QR код)
        if args:
            qr_hash = args
            # Ищем код в базе
            q_stmt = select(QRCode).where(QRCode.code_hash == qr_hash)
            q_res = await session.execute(q_stmt)
            qr = q_res.scalar_one_or_none()

            # --- БЛОК ПРОВЕРОК ---
            if not qr:
                await message.answer("❌ Неверный QR-код.")
                return

            if not qr.is_active:
                await message.answer("❌ Этот код деактивирован администратором.")
                return

            if qr.activated_at:
                # Код уже кем-то активирован
                if qr.activated_by_id == user_id:
                    await message.answer("ℹ️ Вы уже активировали этот код ранее.")
                else:
                    await message.answer("❌ Этот код уже использован другим пользователем.")
                
                # Показываем меню (передаем счетчик для кнопки Натальной карты)
                await message.answer("🏠 Главное меню:", reply_markup=get_main_menu(qr_activations=user.qr_activations_count))
                return
            
            # --- АКТИВАЦИЯ ---
            now = datetime.datetime.now(datetime.timezone.utc)
            
            # Обновляем QR
            qr.activated_at = now
            qr.activated_by_id = user_id
            
            # Логика счетчика
            user.qr_activations_count += 1
            
            # Обновляем Подписку Юзера
            if user.subscription_expires_at and user.subscription_expires_at > now:
                user.subscription_expires_at += datetime.timedelta(days=5)
            else:
                user.subscription_expires_at = now + datetime.timedelta(days=5)
            
            await session.commit()
            
            expires_str = user.subscription_expires_at.strftime("%d.%m.%Y")
            
            await message.answer(
                f"✅ <b>Доступ активирован!</b>\nДействует до: {expires_str}\n\nВыберите режим ниже 👇",
                reply_markup=get_main_menu(qr_activations=user.qr_activations_count)
            )
            
            # Проверка достижения
            if user.qr_activations_count == 3:
                await message.answer(
                    "🎉 <b>Особое достижение!</b>\n\nВы активировали 3 QR-кода и открыли доступ к составлению **Натальной Карты**.\n"
                    "Эта функция теперь доступна в главном меню в разделе 'Астролог'."
                )
            return

        # 3. Если просто /start без кода
        now = datetime.datetime.now(datetime.timezone.utc)

        if user.subscription_expires_at and user.subscription_expires_at > now:
             await message.answer("🏠 Главное меню:", reply_markup=get_main_menu(qr_activations=user.qr_activations_count))
        else:
             await message.answer("👋 Привет! Я REX Bot.\nДля доступа к диетологу и тренировкам отсканируйте QR-код с упаковки.")

# --- ЗАПУСК ---
async def main():
    storage = RedisStorage(redis=redis_client)
    
    bot = Bot(
        token=settings.BOT_TOKEN.get_secret_value(), 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=storage)

    # ПОДКЛЮЧАЕМ РОУТЕРЫ
    # Порядок важен: сначала специфичные, потом общие (survey ловит все mode_)
    dp.include_router(tracking_router.router)
    dp.include_router(dating_router.router)
    dp.include_router(profile_router.router)
    dp.include_router(survey_router.router)
    
    dp.message.register(start_handler, CommandStart())

    print("🤖 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())