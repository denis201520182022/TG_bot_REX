from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def get_main_menu(natal_credits: int = 0, is_admin: bool = False) -> ReplyKeyboardMarkup:
    """
    Главное меню бота (внизу экрана).
    Принимает natal_credits (баланс попыток для натальной карты).
    """
    
    # Ряд 1: Основные сервисы
    row1 = [
        KeyboardButton(text="🥦 Диетолог"),
        KeyboardButton(text="💪 Тренер")
    ]
    
    # Ряд 2: Доп. сервисы
    row2 = [
        KeyboardButton(text="❤️ Найти партнера"),
        KeyboardButton(text="🔮 Астро-прогноз")
    ]
    
    # Ряд 3: Условная кнопка (Натальная карта)
    row3 = []
    # Показываем кнопку, если есть хотя бы 1 кредит
    if natal_credits > 0:
        row3.append(KeyboardButton(text=f"🌟 Натальная карта ({natal_credits})"))

    # Ряд 4: Сервисные кнопки
    row4 = [
        KeyboardButton(text="ℹ️ Справка")
    ]
    
    # Ряд 5: Админка
    row5 = []
    if is_admin:
        row5.append(KeyboardButton(text="🔒 Админка"))

    keyboard = [row1, row2]
    if row3: keyboard.append(row3)
    keyboard.append(row4)
    if row5: keyboard.append(row5)

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите режим в меню 👇"
    )

def get_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Прервать анкету", callback_data="cancel_survey")]
    ])