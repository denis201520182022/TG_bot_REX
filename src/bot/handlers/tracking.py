import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select, desc, and_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from prometheus_client import Counter

from src.database.session import async_session_maker
from src.database.models import DailyTracking

# --- OBSERVABILITY ---
from src.utils.logger import logger
from src.utils.alerting import send_alert

router = Router()

# --- МЕТРИКИ ---
# Считаем активность пользователей по трекингу
TRACKING_SUBMISSIONS = Counter(
    'rex_tracking_submissions_total', 
    'Total daily tracking submissions', 
    ['mode', 'status']
)
# Считаем достижения (удержание)
STREAK_MILESTONES = Counter(
    'rex_streak_milestones_total', 
    'Total streaks reached milestone', 
    ['mode', 'days']
)

# --- ВСПОМОГАТЕЛЬНАЯ ЛОГИКА ---

async def _calculate_streak(session: Session, user_id: int, mode: str) -> int:
    """Считает серию дней для конкретного режима ('diet' или 'trainer')."""
    stmt = select(DailyTracking).where(
        and_(
            DailyTracking.user_id == user_id,
            DailyTracking.mode == mode
        )
    ).order_by(desc(DailyTracking.date))
    
    result = await session.execute(stmt)
    history = result.scalars().all()
    
    if not history: return 0

    streak = 0
    check_date = datetime.date.today()
    
    for record in history:
        if record.date > check_date: continue
        
        if record.date == check_date and record.status in ['success', 'partial']:
            streak += 1
            check_date -= datetime.timedelta(days=1)
        elif record.date < check_date:
            break
        else:
            break
            
    return streak

# --- ХЕНДЛЕРЫ ЕЖЕДНЕВНОГО ОТЧЕТА ---

@router.callback_query(F.data.startswith("track_"))
async def process_daily_track(callback: CallbackQuery):
    try:
        # data format: track_diet_success
        _, mode, status = callback.data.split("_")
        user_id = callback.from_user.id
        today = datetime.date.today()
        
        # Логгер с контекстом
        log = logger.bind(user_id=user_id, mode=mode, status=status, worker="bot_handler")
        
        await callback.message.edit_reply_markup(reply_markup=None)
        
        async with async_session_maker() as session:
            # 1. Защита от повторного ответа
            try:
                existing_stmt = select(DailyTracking).where(
                    and_(DailyTracking.user_id == user_id, DailyTracking.date == today, DailyTracking.mode == mode)
                )
                if (await session.execute(existing_stmt)).scalar_one_or_none():
                    log.warning("tracking_duplicate_attempt")
                    return await callback.answer("Вы уже отметились сегодня по этому направлению.", show_alert=True)

                # 2. Сохраняем
                track = DailyTracking(user_id=user_id, status=status, date=today, mode=mode)
                session.add(track)
                await session.commit()
                
                # Метрика: Запись сохранена
                TRACKING_SUBMISSIONS.labels(mode=mode, status=status).inc()
                log.info("tracking_saved")

            except IntegrityError:
                await session.rollback()
                log.warning("tracking_integrity_error")
                return await callback.answer("Ошибка сохранения.", show_alert=True)
            
            # 3. Считаем стрик для этого режима
            current_streak = await _calculate_streak(session, user_id, mode)
            
            # 4. Выдача награды
            if current_streak == 7:
                log.info("streak_milestone_reached", days=7)
                STREAK_MILESTONES.labels(mode=mode, days="7").inc()
                
                await callback.message.answer(
                    "🎉 <b>НЕДЕЛЯ ПОБЕД!</b>\n"
                    f"Вы 7 дней подряд следуете плану ({'питание' if mode == 'diet' else 'тренировки'}).\n\n"
                    "🎁 Ваш промокод: <code>HEALTH7DAY</code>"
                )

        # 5. Ответ пользователю
        msg_text = ""
        if status == 'success':
            msg_text = f"🔥 Отлично! Серия ({mode}): {current_streak} дн."
        elif status == 'partial':
            msg_text = f"👍 Принято. Серия ({mode}): {current_streak} дн."
        else:
            msg_text = f"Ничего, завтра наверстаете! Серия ({mode}) сброшена."

        await callback.message.edit_text(callback.message.text + f"\n\n<b>Итог: {msg_text}</b>")
        await callback.answer()

    except Exception as e:
        logger.error("tracking_process_failed", error=str(e), user_id=callback.from_user.id)
        await send_alert(e, context="Tracking Handler")
        await callback.answer("Произошла ошибка при сохранении.", show_alert=True)

# --- Хендлер для кнопки-пустышки ---
@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    try:
        await callback.message.delete()
        # Логируем отказ/игнор (полезно для аналитики конверсии)
        logger.info("tracking_offer_ignored", user_id=callback.from_user.id)
    except:
        pass 
    await callback.answer()