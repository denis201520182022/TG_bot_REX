import asyncio
import sys
import datetime
from os.path import abspath, dirname
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, func, and_, or_

# --- НАСТРОЙКА ПУТЕЙ ---
sys.path.insert(0, dirname(dirname(dirname(abspath(__file__)))))

# --- ИМПОРТЫ ---
from src.config import settings
from src.services.llm import generate_response
from src.services.horoscope import RUS_SIGNS
from src.database.models import User, DailyTracking
from src.database.session import async_session_maker
from src.services.rabbit import send_to_queue
from src.scripts.update_surveys import update_surveys
from src.services.matching import run_daily_matching
from src.services.redis import redis_service
from src.utils.text import clean_html_for_telegram # <--- Убедись, что этот файл создан (см. прошлые ответы)

# --- OBSERVABILITY ---
from src.utils.logger import logger
from src.utils.metrics import start_metrics_server, SCHEDULER_JOBS_RUN, SYSTEM_ERRORS
from src.utils.alerting import send_alert

# --- ОБЕРТКА ДЛЯ ЗАДАЧ ---
async def safe_job_run(job_func, job_id, *args, **kwargs):
    log = logger.bind(job_id=job_id, worker="scheduler")
    log.info("job_started")
    try:
        await job_func(*args, **kwargs)
        SCHEDULER_JOBS_RUN.labels(job_id=job_id, status="success").inc()
        log.info("job_completed")
    except Exception as e:
        SCHEDULER_JOBS_RUN.labels(job_id=job_id, status="error").inc()
        SYSTEM_ERRORS.labels(service="scheduler", error_type=type(e).__name__).inc()
        log.error("job_failed", error=str(e))
        await send_alert(e, context=f"Scheduler Job: {job_id}")

# --- ЗАДАЧИ ---

async def tick():
    pass

async def generate_daily_horoscopes():
    """Генерирует гороскопы с умными ретраями для обхода Rate Limits (429)."""
    logger.info("horoscope_generation_started")
    base_prompt = await redis_service.get_prompt("horoscope") or "Ты астролог. Составь краткий гороскоп для {sign}."
    current_date_str = datetime.date.today().strftime("%d.%m.%Y")
    
    for sign_en, sign_ru in RUS_SIGNS.items():
        # Попытки для каждого знака
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 1. Подготовка
                try:
                    system_text = base_prompt.format(sign=sign_ru, current_date=current_date_str)
                except:
                    system_text = base_prompt.replace("{sign}", sign_ru)
                
                user_content = (
                    f"Гороскоп для знака {sign_ru}. "
                    "Используй <b>жирный шрифт</b>. Добавь эмодзи. Не используй Markdown."
                )
                
                # 2. Генерация
                raw_text = await generate_response(system_text, user_content)
                clean_text = clean_html_for_telegram(raw_text)
                final_text = f"<blockquote expandable>{clean_text}</blockquote>"
                
                # 3. Сохранение
                await redis_service.set_horoscope(sign_en, final_text)
                logger.info("horoscope_generated", sign=sign_en)
                
                # УСПЕХ: Ждем 20 секунд перед следующим знаком (чтобы не злить API) и выходим из цикла ретраев
                await asyncio.sleep(20)
                break 

            except Exception as e:
                error_str = str(e)
                # Если ошибка лимитов (429)
                if "429" in error_str or "Rate limit" in error_str:
                    wait_time = 60 * (attempt + 1) # 60 сек, 120 сек...
                    logger.warning("rate_limit_hit", sign=sign_en, attempt=attempt+1, wait=wait_time)
                    await asyncio.sleep(wait_time)
                    # Цикл продолжится, попробуем снова
                else:
                    # Если другая ошибка - логируем и пропускаем знак
                    logger.error("horoscope_generation_failed", sign=sign_en, error=error_str)
                    break


async def send_diet_checkin():
    logger.info("diet_checkin_started")
    async with async_session_maker() as session:
        stmt = select(User).where(
            and_(User.subscription_expires_at > func.now(), User.is_diet_tracking == True)
        )
        users = (await session.execute(stmt)).scalars().all()
        
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Всё по плану", "callback_data": "track_diet_success"},
                {"text": "⚠️ Частично", "callback_data": "track_diet_partial"},
                {"text": "❌ Срыв", "callback_data": "track_diet_fail"}
            ]]
        }

        count = 0
        for user in users:
            msg = {"user_id": user.user_id, "text": "🥦 <b>Вечерний отчет:</b>\nКак прошел день по питанию?", "keyboard": keyboard}
            await send_to_queue("q_notifications", msg)
            count += 1
        logger.info("diet_checkin_completed", sent_count=count)

async def send_trainer_checkin():
    logger.info("trainer_checkin_started")
    async with async_session_maker() as session:
        stmt = select(User).where(
            and_(User.subscription_expires_at > func.now(), User.is_trainer_tracking == True)
        )
        users = (await session.execute(stmt)).scalars().all()
        
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Тренировка была!", "callback_data": "track_trainer_success"},
                {"text": "⚠️ Не полностью", "callback_data": "track_trainer_partial"},
                {"text": "❌ Пропустил(а)", "callback_data": "track_trainer_fail"}
            ]]
        }

        count = 0
        for user in users:
            msg = {"user_id": user.user_id, "text": "💪 <b>Вечерний отчет:</b>\nБыла ли тренировка?", "keyboard": keyboard}
            await send_to_queue("q_notifications", msg)
            count += 1
        logger.info("trainer_checkin_completed", sent_count=count)

async def run_weekly_report():
    logger.info("weekly_report_started")
    
    async with async_session_maker() as session:
        stmt = select(User).where(
            and_(
                User.subscription_expires_at > func.now(),
                or_(User.is_diet_tracking == True, User.is_trainer_tracking == True)
            )
        )
        users = (await session.execute(stmt)).scalars().all()
        
        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)
        
        count = 0
        for user in users:
            stats_stmt = select(DailyTracking).where(
                and_(
                    DailyTracking.user_id == user.user_id,
                    DailyTracking.date >= week_ago
                )
            )
            records = (await session.execute(stats_stmt)).scalars().all()
            
            if not records: continue

            diet_recs = [r for r in records if r.mode == 'diet']
            trainer_recs = [r for r in records if r.mode == 'trainer']
            
            def format_block(title, recs):
                if not recs: return ""
                s = sum(1 for r in recs if r.status == 'success')
                p = sum(1 for r in recs if r.status == 'partial')
                f = sum(1 for r in recs if r.status == 'fail')
                return (
                    f"\n<b>{title}</b>\n"
                    f"✅ Успех: {s}\n"
                    f"⚠️ Частично: {p}\n"
                    f"❌ Пропуски: {f}\n"
                )

            report_text = f"📊 <b>Ваш отчет за неделю:</b>\n"
            has_data = False
            if user.is_diet_tracking:
                report_text += format_block("🥦 Питание", diet_recs)
                has_data = True
            
            if user.is_trainer_tracking:
                report_text += format_block("💪 Спорт", trainer_recs)
                has_data = True
            
            if not has_data: continue

            total_good = sum(1 for r in records if r.status in ['success', 'partial'])
            total_recs = len(records)
            
            if total_recs > 0:
                ratio = total_good / total_recs
                if ratio >= 0.8: report_text += "\n🔥 <b>Потрясающий результат!</b>"
                elif ratio >= 0.5: report_text += "\n👍 <b>Хороший темп.</b>"
                else: report_text += "\n💪 <b>Не сдавайтесь!</b>"

            await send_to_queue("q_notifications", {"user_id": user.user_id, "text": report_text})
            count += 1
            
        logger.info("weekly_report_completed", sent_count=count)

async def main():
    logger.info("service_started", service="scheduler")
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    
    scheduler.add_job(safe_job_run, 'interval', minutes=10, args=[update_surveys, 'update_surveys'])
    scheduler.add_job(safe_job_run, 'cron', hour=8, minute=0, args=[generate_daily_horoscopes, 'horoscopes'])
    scheduler.add_job(safe_job_run, 'cron', hour=12, minute=0, args=[run_daily_matching, 'dating'])
    scheduler.add_job(safe_job_run, 'cron', hour=20, minute=0, args=[send_diet_checkin, 'diet_checkin'])
    scheduler.add_job(safe_job_run, 'cron', hour=20, minute=1, args=[send_trainer_checkin, 'trainer_checkin'])
    scheduler.add_job(safe_job_run, 'cron', day_of_week='sun', hour=21, minute=0, args=[run_weekly_report, 'weekly_report'])

    scheduler.start()
    
    try:
        logger.info("initial_sync_started")
        await update_surveys()
    except Exception as e:
        logger.error("initial_sync_failed", error=str(e))

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    start_metrics_server(8003)
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("service_stopped")