from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select, func, and_

from src.database.session import async_session_maker
from src.database.models import User, QRCode, UserSurvey, DatingMatch
from src.config import settings

router = Router()

# Список админов из конфига
def get_admin_ids():
    return [int(x) for x in settings.ADMIN_IDS.split(',')]

# Фильтр: пускаем только админов
router.message.filter(F.from_user.id.in_(get_admin_ids()))

@router.message(F.text == "🔒 Админка")
async def admin_menu(message: Message):
    """Показывает статистику проекта."""
    
    async with async_session_maker() as session:
        # 1. Всего пользователей
        total_users = await session.scalar(select(func.count(User.user_id)))
        
        # 2. Активные подписки (у кого дата истечения в будущем)
        active_subs = await session.scalar(
            select(func.count(User.user_id)).where(User.subscription_expires_at > func.now())
        )
        
        # 3. Активированные QR коды
        activated_qrs = await session.scalar(
            select(func.count(QRCode.code_hash)).where(QRCode.activated_at.is_not(None))
        )
        
        # 4. Всего QR кодов
        total_qrs = await session.scalar(select(func.count(QRCode.code_hash)))
        
        # 5. Заполнено анкет (Всего)
        total_surveys = await session.scalar(select(func.count(UserSurvey.id)))
        
        # 6. Мэтчи в дейтинге
        matches = await session.scalar(
            select(func.count(DatingMatch.id)).where(DatingMatch.is_match == True)
        )

    text = (
        "📊 <b>Статистика REX Bot:</b>\n\n"
        f"👥 <b>Пользователи:</b> {total_users}\n"
        f"✅ <b>Активные подписки:</b> {active_subs}\n\n"
        f"🎫 <b>QR-коды:</b> {activated_qrs} / {total_qrs}\n"
        f"📝 <b>Заполнено анкет:</b> {total_surveys}\n"
        f"💘 <b>Сложилось пар:</b> {matches}\n"
    )
    
    await message.answer(text)