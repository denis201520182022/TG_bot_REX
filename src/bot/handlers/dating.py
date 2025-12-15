from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from prometheus_client import Counter

from src.database.session import async_session_maker
from src.database.models import DatingMatch, User
from src.bot.keyboards.dating import get_contact_kb
from src.services.rabbit import send_to_queue

# --- OBSERVABILITY ---
from src.utils.logger import logger
from src.utils.alerting import send_alert

router = Router()

# --- МЕТРИКИ ---
DATING_INTERACTIONS = Counter('rex_dating_interactions_total', 'Total dating actions', ['action'])
DATING_MATCHES = Counter('rex_dating_matches_new_total', 'Total mutual matches found')

# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: Создание записи в БД ---
async def _create_interaction_record(session: Session, user_id: int, target_user_id: int, action: str) -> bool:
    """
    Проверяет, было ли уже взаимодействие, и создает новую запись.
    Возвращает True если успешно, False если запись уже была.
    """
    # 1. Проверяем, голосовал ли юзер уже
    existing = await session.execute(
        select(DatingMatch).where(
            and_(DatingMatch.user_id == user_id, DatingMatch.target_user_id == target_user_id)
        )
    )
    if existing.scalar_one_or_none():
        return False # Уже голосовал

    # 2. Создаем новую запись
    record = DatingMatch(user_id=user_id, target_user_id=target_user_id, action=action)
    session.add(record)
    return True

# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: Формирование упоминания ---
def _get_user_mention(user: User) -> str:
    """Возвращает @username если есть, иначе full_name."""
    return f"@{user.username}" if user.username else user.full_name


# --- ХЕНДЛЕРЫ ---

@router.callback_query(F.data.startswith("like_"))
async def process_like(callback: CallbackQuery):
    try:
        target_user_id = int(callback.data.split("_")[1])
        user_id = callback.from_user.id

        # Логгер с контекстом
        log = logger.bind(user_id=user_id, target_id=target_user_id, action="like")

        if target_user_id == user_id:
            return await callback.answer("Себя лайкать нельзя 😅")

        async with async_session_maker() as session:
            # 1. Создаем запись о лайке (с проверкой)
            if not await _create_interaction_record(session, user_id, target_user_id, "like"):
                return await callback.answer("Вы уже голосовали за эту анкету.")

            # 2. Проверяем взаимность
            mutual_like_stmt = select(DatingMatch).where(
                and_(DatingMatch.user_id == target_user_id, DatingMatch.target_user_id == user_id, DatingMatch.action == "like")
            )
            mutual_like = (await session.execute(mutual_like_stmt)).scalar_one_or_none()

            is_match = False
            if mutual_like:
                is_match = True
                # Обновляем обе записи в БД, помечая их как мэтч
                stmt = select(DatingMatch).where(and_(DatingMatch.user_id == user_id, DatingMatch.target_user_id == target_user_id))
                my_like_res = await session.execute(stmt)
                my_like_record = my_like_res.scalar_one_or_none()

                if my_like_record: my_like_record.is_match = True
                mutual_like.is_match = True
            
            await session.commit()

            # Метрики и логи
            DATING_INTERACTIONS.labels(action="like").inc()
            log.info("dating_like_processed", is_match=is_match)

            # 3. Реакция интерфейса
            await callback.answer("❤️ Лайк отправлен!")
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("Анкета обработана. Ждите следующую подборку завтра!")

            # 4. Если Мэтч — отправляем уведомления
            if is_match:
                DATING_MATCHES.inc()
                
                # Получаем данные обоих юзеров для красивых уведомлений
                me = await session.get(User, user_id)
                target = await session.get(User, target_user_id)

                if not me or not target: 
                    log.warning("match_user_not_found_in_db")
                    return

                # Уведомление мне
                await callback.message.answer(
                    f"🎉 <b>IT'S A MATCH!</b>\nВам ответил(а) взаимностью {_get_user_mention(target)}!",
                    reply_markup=get_contact_kb(target.username)
                )
                
                # Уведомление ему (через очередь)
                notification = {
                    "user_id": target_user_id,
                    "text": f"🎉 <b>У вас новое совпадение!</b>\nПользователь {_get_user_mention(me)} ответил взаимностью!",
                    "keyboard": get_contact_kb(me.username).model_dump()
                }
                await send_to_queue("q_notifications", notification)
                log.info("match_notifications_sent")

    except Exception as e:
        logger.error("dating_like_error", error=str(e), user_id=callback.from_user.id)
        await send_alert(e, context="Dating Like Handler")
        await callback.answer("Ошибка обработки лайка", show_alert=True)


@router.callback_query(F.data.startswith("dislike_"))
async def process_dislike(callback: CallbackQuery):
    try:
        target_user_id = int(callback.data.split("_")[1])
        user_id = callback.from_user.id
        
        log = logger.bind(user_id=user_id, target_id=target_user_id, action="dislike")

        async with async_session_maker() as session:
            # Создаем запись о дизлайке (с проверкой)
            if not await _create_interaction_record(session, user_id, target_user_id, "dislike"):
                return await callback.answer("Вы уже голосовали за эту анкету.")
            await session.commit()

        # Метрики
        DATING_INTERACTIONS.labels(action="dislike").inc()
        log.info("dating_dislike_processed")

        await callback.answer("👎 Анкета скрыта.")
        await callback.message.edit_text("🚫 Вы пропустили эту анкету.")
        
    except Exception as e:
        logger.error("dating_dislike_error", error=str(e), user_id=callback.from_user.id)
        await send_alert(e, context="Dating Dislike Handler")
        await callback.answer("Ошибка обработки", show_alert=True)