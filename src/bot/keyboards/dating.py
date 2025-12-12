from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_dating_kb(target_user_id: int) -> InlineKeyboardMarkup:
    """
    Кнопки под анкетой кандидата.
    В callback_data зашиваем ID того, кого лайкаем.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❤️ Лайк", callback_data=f"like_{target_user_id}"),
            InlineKeyboardButton(text="👎 Пропустить", callback_data=f"dislike_{target_user_id}")
        ],
        [
            InlineKeyboardButton(text="⚠️ Пожаловаться", callback_data=f"report_{target_user_id}")
        ]
    ])

def get_contact_kb(username: str) -> InlineKeyboardMarkup:
    """Кнопка связи при совпадении"""
    url = f"https://t.me/{username}" if username else "https://t.me/"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать партнеру", url=url)]
    ])