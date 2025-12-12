from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_menu(qr_activations: int = 0) -> ReplyKeyboardMarkup:
    """
    Главное меню бота (внизу экрана).
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
    if qr_activations >= 3:
        row3.append(KeyboardButton(text="🌟 Натальная карта"))

    # Ряд 4: Сервисные кнопки
    # "Справка" вместо "Поддержки"
    row4 = [
        KeyboardButton(text="✏️ Изменить анкету"),
        KeyboardButton(text="ℹ️ Справка")
    ]

    keyboard = [row1, row2]
    if row3:
        keyboard.append(row3)
    keyboard.append(row4)

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True, # Кнопки компактные
        input_field_placeholder="Выберите режим в меню 👇"
    )

# Для "отмены" внутри анкеты лучше оставить Inline (под сообщением), 
# так как Reply-кнопки "Отмена" часто путаются с главным меню.
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
def get_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Прервать анкету", callback_data="cancel_survey")]
    ])