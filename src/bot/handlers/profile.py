from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from src.database.session import async_session_maker
from src.database.models import User
from src.bot.keyboards.menu import get_main_menu

router = Router()

# Клавиатура выбора анкеты для редактирования
# Обрати внимание: callback_data совпадает с теми, что в главном меню.
# Это значит, что при нажатии сработает survey.py и запустит анкету заново.
edit_menu_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🥦 Диетолог", callback_data="mode_diet")],
    [InlineKeyboardButton(text="💪 Тренер", callback_data="mode_trainer")],
    [InlineKeyboardButton(text="❤️ Знакомства", callback_data="mode_dating")],
    [InlineKeyboardButton(text="🔮 Астролог (Данные)", callback_data="mode_horoscope")],
    [InlineKeyboardButton(text="↩️ Назад в меню", callback_data="back_to_main_menu")]
])

@router.callback_query(F.data == "edit_profile")
async def edit_profile_menu(callback: CallbackQuery):
    """Показывает меню выбора, какую анкету перезаполнить."""
    await callback.message.edit_text(
        "Какую анкету вы хотите заполнить заново?",
        reply_markup=edit_menu_kb
    )
    await callback.answer()

@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu(callback: CallbackQuery):
    """Возвращает в главное меню."""
    # Нам нужно узнать qr_activations, чтобы правильно отрисовать меню
    user_id = callback.from_user.id
    
    activations = 0
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        if user:
            activations = user.qr_activations_count

    await callback.message.edit_text(
        "🏠 Главное меню:", 
        reply_markup=get_main_menu(qr_activations=activations)
    )
    await callback.answer()