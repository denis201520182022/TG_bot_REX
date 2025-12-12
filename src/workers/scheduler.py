import asyncio
import sys
import datetime
from os.path import abspath, dirname
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, func, and_

# --- НАСТРОЙКА ПУТЕЙ (ВАЖНО) ---
# Эта секция позволяет запускать скрипт напрямую и видеть другие папки (src/services, src/database)
sys.path.insert(0, dirname(dirname(dirname(abspath(__file__)))))

# --- ИМПОРТЫ КОМПОНЕНТОВ ПРОЕКТА ---
from src.config import settings
from src.services.llm import generate_response
from src.services.horoscope import RUS_SIGNS
from src.database.models import User, DailyTracking
from src.database.session import async_session_maker
from src.services.rabbit import send_to_queue
from src.scripts.update_surveys import update_surveys
from src.services.matching import run_daily_matching
from src.services.redis import redis_service

# --- ФУНКЦИИ-ЗАДАЧИ ДЛЯ ПЛАНИРОВЩИКА ---

async def tick():
    """Простая задача, которая выполняется каждую минуту, чтобы показать, что планировщик работает."""
    print("⏰ Tick! Планировщик жив...")

async def generate_daily_horoscopes():
    """Генерирует гороскопы для всех знаков зодиака и кэширует их в Redis на 24 часа."""
    print("🔮 Генерация гороскопов на сегодня...")
    base_prompt = await redis_service.get_prompt("horoscope") or "Ты астролог. Составь краткий гороскоп на сегодня для знака {sign}."
    
    for sign_en, sign_ru in RUS_SIGNS.items():
        try:
            system_text = base_prompt.format(sign=sign_ru)
            text = await generate_response(system_text, "Гороскоп на сегодня.")
            await redis_service.set_horoscope(sign_en, text)
            print(f"✅ Гороскоп для {sign_en} готов.")
        except Exception as e:
            print(f"❌ Ошибка генерации гороскопа для {sign_en}: {e}")

async def send_diet_checkin():
    """Отправляет вечерний опрос по ПИТАНИЮ тем, кто подписался."""
    print("🥦 Запуск вечернего опроса по ПИТАНИЮ...")
    async with async_session_maker() as session:
        stmt = select(User).where(
            and_(User.subscription_expires_at > func.now(), User.is_diet_tracking == True)
        )
        users = (await session.execute(stmt)).scalars().all()
        
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Всё по плану", "callback_data": "track_diet_success"},
                {"text": "⚠️ Частично", "callback_data": "track_diet_partial"},
                {"text": "❌ Не получилось", "callback_data": "track_diet_fail"}
            ]]
        }

        count = 0
        for user in users:
            msg = {
                "user_id": user.user_id,
                "text": "🌙 Привет! Как прошел день? Удалось придерживаться плана ПИТАНИЯ?",
                "keyboard": keyboard
            }
            await send_to_queue("q_notifications", msg)
            count += 1
        print(f"📨 Отправлено {count} опросов по питанию.")

async def send_trainer_checkin():
    """Отправляет вечерний опрос по ТРЕНИРОВКАМ тем, кто подписался."""
    print("💪 Запуск вечернего опроса по ТРЕНИРОВКАМ...")
    async with async_session_maker() as session:
        stmt = select(User).where(
            and_(User.subscription_expires_at > func.now(), User.is_trainer_tracking == True)
        )
        users = (await session.execute(stmt)).scalars().all()
        
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Тренировка была!", "callback_data": "track_trainer_success"},
                {"text": "⚠️ Частично", "callback_data": "track_trainer_partial"},
                {"text": "❌ Пропустил(а)", "callback_data": "track_trainer_fail"}
            ]]
        }

        count = 0
        for user in users:
            msg = {
                "user_id": user.user_id,
                "text": "🌙 Как успехи с ТРЕНИРОВКАМИ сегодня?",
                "keyboard": keyboard
            }
            await send_to_queue("q_notifications", msg)
            count += 1
        print(f"📨 Отправлено {count} опросов по тренировкам.")

async def run_weekly_report():
    """Формирует и отправляет еженедельные отчеты о прогрессе."""
    print("📊 Формирование еженедельных отчетов...")
    async with async_session_maker() as session:
        # Отчет отправляется всем, у кого включен хотя бы один вид трекинга
        stmt = select(User).where(
            (User.is_diet_tracking == True) | (User.is_trainer_tracking == True)
        )
        users = (await session.execute(stmt)).scalars().all()
        week_ago = datetime.date.today() - datetime.timedelta(days=7)
        
        count = 0
        for user in users:
            stats_stmt = select(DailyTracking.status, func.count(DailyTracking.id)).where(
                and_(DailyTracking.user_id == user.user_id, DailyTracking.date >= week_ago)
            ).group_by(DailyTracking.status)
            stats_res = (await session.execute(stats_stmt)).all()
            stats = {row[0]: row[1] for row in stats_res}
            
            success, partial, fail = stats.get('success', 0), stats.get('partial', 0), stats.get('fail', 0)
            if (success + partial + fail) == 0: continue
            
            report_text = f"📅 <b>Ваша неделя в цифрах:</b>\n\n✅ Выполнено: {success}\n⚠️ Частично: {partial}\n❌ Пропущено: {fail}\n\n"
            if success >= 5: report_text += "🔥 Отличный результат!"
            elif success >= 3: report_text += "👍 Хороший темп!"
            else: report_text += "💪 Не сдавайтесь!"

            await send_to_queue("q_notifications", {"user_id": user.user_id, "text": report_text})
            count += 1
        print(f"📊 Отправлено {count} отчетов.")

# --- ОСНОВНАЯ ФУНКЦИЯ ЗАПУСКА ---
async def main():
    print("📅 Scheduler Worker запускается...")
    
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow") # Явно указываем часовой пояс
    
    # --- СИСТЕМНЫЕ ЗАДАЧИ ---
    scheduler.add_job(update_surveys, 'interval', minutes=10, id='update_surveys')
    scheduler.add_job(tick, 'interval', minutes=1, id='tick')
    
    # --- БИЗНЕС-ЗАДАЧИ ПО РАСПИСАНИЮ ---
    scheduler.add_job(generate_daily_horoscopes, 'cron', hour=8, minute=0, id='horoscopes')
    scheduler.add_job(run_daily_matching, 'cron', hour=12, minute=0, id='dating')
    scheduler.add_job(send_diet_checkin, 'cron', hour=20, minute=0, id='diet_checkin')
    scheduler.add_job(send_trainer_checkin, 'cron', hour=20, minute=1, id='trainer_checkin')
    scheduler.add_job(run_weekly_report, 'cron', day_of_week='sun', hour=21, minute=0, id='weekly_report')

    scheduler.start()
    
    # При старте воркера один раз синхронизируем конфиги
    print("🔄 Первичная синхронизация с Google Sheets...")
    await update_surveys()

    # Бесконечный цикл для поддержания работы процесса
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())