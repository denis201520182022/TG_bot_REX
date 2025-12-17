import asyncio
import sys
import datetime
from os.path import abspath, dirname

# Пути
sys.path.insert(0, dirname(dirname(dirname(abspath(__file__)))))

from aiogram import Bot, Dispatcher, Router, F
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import settings
from src.database.session import async_session_maker
from src.database.models import User, QRCode
from sqlalchemy import select
from src.services.redis import redis_client

# --- OBSERVABILITY ---
from src.utils.logger import logger
from src.utils.metrics import start_metrics_server, USER_UPDATES
from src.utils.alerting import send_alert

# ИМПОРТЫ РОУТЕРОВ
from src.bot.keyboards.menu import get_main_menu
from src.bot.handlers import survey as survey_router
from src.bot.handlers import dating as dating_router
from src.bot.handlers import tracking as tracking_router
from src.bot.handlers import profile as profile_router 
from src.bot.handlers import admin as admin_router

from src.bot.middlewares.check_sub import CheckSubscriptionMiddleware

# Хелпер для проверки админа
def is_admin(user_id: int) -> bool:
    try:
        admin_ids = [int(x) for x in settings.ADMIN_IDS.split(',')]
        return user_id in admin_ids
    except:
        return False

async def start_handler(message: Message, command: CommandObject):
    args = command.args 
    user_id = message.from_user.id
    
    log = logger.bind(user_id=user_id, command="start")
    USER_UPDATES.labels(type="command_start").inc()
    
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
            log.info("new_user_registered")

        # --- ЛОГИКА ДЛЯ АДМИНА (Full Access) ---
        if is_admin(user_id):
            menu_kb = get_main_menu(natal_credits=999, is_admin=True) # Админу даем визуально 999
            await message.answer(
                "👋 Привет, Админ! У вас полный доступ без ограничений.", 
                reply_markup=menu_kb
            )
            return
        # ---------------------------------------

        # Получаем меню для обычного юзера
        menu_kb = get_main_menu(
            natal_credits=user.natal_chart_credits, # <--- ИСПРАВЛЕНО
            is_admin=False
        )

        # 2. Активация QR кода
        if args:
            qr_hash = args
            q_stmt = select(QRCode).where(QRCode.code_hash == qr_hash)
            q_res = await session.execute(q_stmt)
            qr = q_res.scalar_one_or_none()

            # --- БЛОК ПРОВЕРОК ---
            if not qr:
                log.warning("invalid_qr_attempt", code_hash=qr_hash)
                await message.answer("❌ Неверный QR-код.")
                return

            if not qr.is_active:
                log.warning("inactive_qr_attempt", code_hash=qr_hash)
                await message.answer("❌ Этот код деактивирован администратором.")
                return

            if qr.activated_at:
                if qr.activated_by_id == user_id:
                    await message.answer("ℹ️ Вы уже активировали этот код ранее.")
                else:
                    log.warning("duplicate_qr_usage_attempt", code_hash=qr_hash)
                    await message.answer("❌ Этот код уже использован другим пользователем.")
                
                await message.answer("🏠 Главное меню:", reply_markup=menu_kb)
                return
            
            # --- АКТИВАЦИЯ ---
            now = datetime.datetime.now(datetime.timezone.utc)
            qr.activated_at = now
            qr.activated_by_id = user_id
            user.qr_activations_count += 1
            
            # Логика начисления КРЕДИТОВ (каждый 3-й код)
            bonus_msg = ""
            # Даем кредит ТОЛЬКО если это 5-я активация
            if user.qr_activations_count == 5:
                user.natal_chart_credits += 1
                bonus_msg = "\n\n🌟 <b>Поздравляем!</b> Вы активировали 5 кодов! Вам доступна <b>Натальная карта</b> (1 раз)."
            elif user.qr_activations_count < 5:
                left = 5 - user.qr_activations_count
                bonus_msg = f"\n\n(Активируйте еще {left} шт., чтобы открыть Натальную карту)"
            # Если > 5, то ничего не пишем и кредиты не даем
            # ----------------------------------------
            # Обновляем подписку
            if user.subscription_expires_at and user.subscription_expires_at > now:
                user.subscription_expires_at += datetime.timedelta(days=5)
            else:
                user.subscription_expires_at = now + datetime.timedelta(days=5)
            
            await session.commit()
            
            log.info("qr_activated_successfully", code_hash=qr_hash, activation_count=user.qr_activations_count)
            
            expires_str = user.subscription_expires_at.strftime("%d.%m.%Y")
            
            # Обновляем меню с учетом НОВЫХ кредитов
            new_menu_kb = get_main_menu(
                natal_credits=user.natal_chart_credits, # <--- ИСПРАВЛЕНО
                is_admin=False
            )
            
            await message.answer(
                f"✅ <b>Доступ активирован!</b>\nДействует до: {expires_str}" + bonus_msg,
                reply_markup=new_menu_kb
            )
            
            return

        # 3. Просто /start без кода
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Проверка подписки для обычных юзеров
        if user.subscription_expires_at and user.subscription_expires_at > now:
             await message.answer("🏠 Главное меню:", reply_markup=menu_kb)
        else:
             await message.answer("👋 Привет! Я REX Bot.\nДля доступа к диетологу и тренировкам отсканируйте QR-код с упаковки.")

# --- ЗАПУСК ---
async def main():
    logger.info("service_started", service="bot_polling")
    
    storage = RedisStorage(redis=redis_client)
    
    bot = Bot(
        token=settings.BOT_TOKEN.get_secret_value(), 
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=storage)

    # --- ПОДКЛЮЧЕНИЕ MIDDLEWARE (ВАЖНО!) ---
    # Ставим его ДО роутеров, чтобы проверять всё
    dp.message.middleware(CheckSubscriptionMiddleware())
    dp.callback_query.middleware(CheckSubscriptionMiddleware())
    # ---------------------------------------

    # ПОДКЛЮЧЕНИЕ РОУТЕРОВ
    # Порядок критически важен:
    # 1. Админка (самый приоритет)
    dp.include_router(admin_router.router)
    # 2. Функциональные роутеры
    dp.include_router(tracking_router.router)
    dp.include_router(dating_router.router)
    dp.include_router(profile_router.router)
    dp.include_router(survey_router.router)
    
    # 3. Регистрация команды /start
    dp.message.register(start_handler, CommandStart())
    
    # Echo handler убран. Бот будет молчать на неизвестные сообщения.

    logger.info("bot_polling_started")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical("bot_crashed", error=str(e))
        await send_alert(e, context="Bot Polling Service")
        raise e

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    start_metrics_server(8002)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("service_stopped")
    except Exception as e:
        pass