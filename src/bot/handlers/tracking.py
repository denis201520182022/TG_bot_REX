import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select, desc, update, and_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.database.session import async_session_maker
from src.database.models import DailyTracking, User

router = Router()

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
    # track_diet_success
    _, mode, status = callback.data.split("_")
    user_id = callback.from_user.id
    today = datetime.date.today()
    
    await callback.message.edit_reply_markup(reply_markup=None)
    
    async with async_session_maker() as session:
        # 1. Защита от повторного ответа
        try:
            existing_stmt = select(DailyTracking).where(
                and_(DailyTracking.user_id == user_id, DailyTracking.date == today, DailyTracking.mode == mode)
            )
            if (await session.execute(existing_stmt)).scalar_one_or_none():
                return await callback.answer("Вы уже отметились сегодня по этому направлению.", show_alert=True)

            # 2. Сохраняем
            track = DailyTracking(user_id=user_id, status=status, date=today, mode=mode)
            session.add(track)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return await callback.answer("Ошибка сохранения.", show_alert=True)
        
        # 3. Считаем стрик для этого режима
        current_streak = await _calculate_streak(session, user_id, mode)
        
        # 4. Выдача награды
        if current_streak == 7:
             # Проверяем, не выдавали ли мы уже промокод за другой стрик
             # (В будущем можно сделать более сложную логику)
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

# --- Хендлер для кнопки-пустышки (когда юзер отказывается от подписки) ---
@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    # Просто удаляем сообщение с кнопками
    try:
        await callback.message.delete()
    except:
        pass # Если не получилось удалить, не страшно
    await callback.answer()