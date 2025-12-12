import json
import datetime
import asyncio
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ContentType
from sqlalchemy import select

# Сервисы и настройки
from src.services.redis import redis_service 
from src.bot.states import SurveyState
from src.bot.keyboards.menu import get_cancel_kb, get_main_menu
from src.database.session import async_session_maker
from src.database.models import UserSurvey, User
from src.services.rabbit import send_to_queue
from src.services.horoscope import get_zodiac_sign, RUS_SIGNS

router = Router()

# --- КОНСТАНТЫ ---
MENU_MAPPING = {
    "🥦 Диетолог": "diet",
    "💪 Тренер": "trainer",
    "❤️ Найти партнера": "dating",
    "🔮 Астро-прогноз": "horoscope",
    "🌟 Натальная карта": "natal_chart"
}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИआई ---

async def show_main_menu(message: Message, text: str, user_id: int):
    """Показывает главное меню."""
    activations = 0
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        if user: activations = user.qr_activations_count
    await message.answer(text, reply_markup=get_main_menu(qr_activations=activations))

# --- ПРОМЕЖУТОЧНОЕ МЕНЮ (ДЛЯ ДИЕТОЛОГА/ТРЕНЕРА) ---

def get_mode_menu_kb(mode: str, is_tracking_on: bool) -> InlineKeyboardMarkup:
    """Генерирует меню для режима 'Диетолог' или 'Тренер'."""
    tracking_text = "✅ Трекинг ВКЛ" if is_tracking_on else "❌ Трекинг ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Заполнить/обновить анкету", callback_data=f"start_survey_{mode}")],
        [InlineKeyboardButton(text=tracking_text, callback_data=f"toggle_tracking_{mode}")]
    ])

# Хендлер для кнопок "Диетолог" и "Тренер" в главном меню
@router.message(F.text.in_(["🥦 Диетолог", "💪 Тренер"]))
async def show_mode_menu(message: Message):
    mode = MENU_MAPPING[message.text]
    async with async_session_maker() as session:
        user = await session.get(User, message.from_user.id)
        if not user: return # На всякий случай
        
        is_tracking = user.is_diet_tracking if mode == 'diet' else user.is_trainer_tracking
    
    await message.answer(
        f"Вы выбрали режим <b>{mode.capitalize()}</b>. Что делаем?",
        reply_markup=get_mode_menu_kb(mode, is_tracking)
    )

# Обработчик кнопки вкл/выкл трекинг
@router.callback_query(F.data.startswith("toggle_tracking_"))
async def toggle_tracking(callback: CallbackQuery):
    mode = callback.data.split("_")[2]
    new_status = False # Значение по умолчанию
    
    async with async_session_maker() as session:
        user = await session.get(User, callback.from_user.id)
        
        if mode == 'diet':
            new_status = not user.is_diet_tracking
            user.is_diet_tracking = new_status
        elif mode == 'trainer':
            new_status = not user.is_trainer_tracking
            user.is_trainer_tracking = new_status
            
        await session.commit()
    
    await callback.message.edit_reply_markup(reply_markup=get_mode_menu_kb(mode, new_status))
    await callback.answer(f"Ежедневный трекинг {'включен' if new_status else 'выключен'}")

# --- ЗАПУСК АНКЕТЫ ---

# 1. Запуск по ТЕКСТУ (Дейтинг, Астролог)
@router.message(F.text.in_(["❤️ Найти партнера", "🔮 Астро-прогноз", "🌟 Натальная карта"]))
async def start_survey_by_text(message: Message, state: FSMContext):
    mode = MENU_MAPPING[message.text]
    await _start_survey_logic(message, state, mode)

# 2. Запуск по КНОПКЕ (из меню "Изменить анкету" или "Заполнить анкету")
@router.callback_query(F.data.startswith(("mode_", "start_survey_")))
async def start_survey_by_callback(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split("_")[-1]
    await _start_survey_logic(callback.message, state, mode)
    await callback.answer()

async def _start_survey_logic(message: Message, state: FSMContext, mode: str):
    questions = await redis_service.get_survey_config(mode)
    if not questions:
        return await message.answer("⚠️ Этот режим еще не настроен.")

    await state.set_state(SurveyState.in_progress)
    await state.update_data(survey_mode=mode, current_step=0, answers={})
    
    first_q = questions[0]
    await message.answer(
        f"📝 <b>Режим: {mode.upper()}</b>\n\nВопрос 1/{len(questions)}:\n{first_q['text']}", 
        reply_markup=get_cancel_kb()
    )

# --- ОТМЕНА, ОБРАБОТКА ОТВЕТОВ, СОГЛАСИЕ ---

@router.callback_query(F.data == "cancel_survey", SurveyState.in_progress)
async def cancel_survey(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Анкета прервана.")
    await show_main_menu(callback.message, "Выберите режим:", callback.from_user.id)

@router.message(SurveyState.in_progress, F.content_type.in_([ContentType.TEXT, ContentType.PHOTO]))
async def process_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    mode, step, answers = data['survey_mode'], data['current_step'], data['answers']
    
    questions = await redis_service.get_survey_config(mode)
    if not questions:
        await message.answer("Ошибка конфигурации.")
        await state.clear()
        return

    current_q = questions[step]
    answer_value = None

    if current_q['type'] == 'photo':
        if not message.photo: return await message.answer("📸 Пожалуйста, отправьте фото.")
        answer_value = message.photo[-1].file_id
    else: 
        if not message.text: return await message.answer("✍️ Введите текст.")
        user_text = message.text.strip()
        if current_q['key'] == 'birth_date':
            try:
                datetime.datetime.strptime(user_text, "%d.%m.%Y").date()
            except ValueError:
                return await message.answer("❗️Неверный формат: ДД.ММ.ГГГГ")
        answer_value = user_text

    answers[current_q['key']] = answer_value
    next_step = step + 1

    if next_step < len(questions):
        await state.update_data(current_step=next_step, answers=answers)
        next_q = questions[next_step]
        text = f"Вопрос {next_step + 1}/{len(questions)}:\n{next_q['text']}"
        if next_q.get('options'): text += f"\n\n(Варианты: {', '.join(next_q['options'])})"
        await message.answer(text, reply_markup=get_cancel_kb())
    else:
        await state.update_data(answers=answers)
        await state.set_state(SurveyState.final_consent)
        consent_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Согласен(а)", callback_data="consent_yes")],
            [InlineKeyboardButton(text="❌ Отказаться", callback_data="consent_no")]
        ])
        await message.answer(
            "📄 <b>Согласие на обработку данных:</b>\n\nПодтвердите согласие на обработку персональных данных для работы сервиса.",
            reply_markup=consent_kb
        )

@router.callback_query(SurveyState.final_consent, F.data.in_(["consent_yes", "consent_no"]))
async def process_consent(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    
    user_id = callback.from_user.id
    
    if callback.data == "consent_no":
        await state.clear()
        await callback.answer("Анкета отменена.", show_alert=True)
        return await show_main_menu(callback.message, "🏠 Главное меню:", user_id)

    data = await state.get_data()
    mode, answers = data['survey_mode'], data['answers']
    await state.clear()
    
    async with async_session_maker() as session:
        # Проверяем, первая ли это анкета для данного режима
        stmt = select(UserSurvey).where(UserSurvey.user_id == user_id, UserSurvey.mode == mode)
        is_first_survey = not (await session.execute(stmt)).scalar_one_or_none()

        # Сохраняем ответы
        new_survey = UserSurvey(user_id=user_id, mode=mode, survey_config_id=1, answers=answers)
        session.add(new_survey)
        await session.flush()
        new_survey_id = new_survey.id
        await session.commit()
    
    # Распределяем логику по режимам
    if mode in ['diet', 'trainer', 'natal_chart']:
        await callback.message.answer(f"✅ <b>Принято!</b>\nИИ анализирует данные... ⏳")
        task_data = {"user_id": user_id, "mode": mode, "answers": answers, "survey_id": new_survey_id}
        await send_to_queue("q_ai_generation", task_data)
        
        if is_first_survey and mode in ['diet', 'trainer']:
            tracking_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👍 Да, хочу следить за прогрессом!", callback_data=f"toggle_tracking_{mode}")],
                [InlineKeyboardButton(text="👎 Нет, спасибо", callback_data="ignore")] # Кнопка-пустышка
            ])
            await asyncio.sleep(1)
            await callback.message.answer(
                "Хотите, чтобы я каждый день в 20:00 спрашивал о ваших успехах в этом режиме?",
                reply_markup=tracking_kb
            )
            
    elif mode == 'dating':
        await callback.message.answer("✅ <b>Анкета знакомств сохранена!</b>\nЖдите предложений в 12:00.")
        
    elif mode == 'horoscope':
        await callback.message.answer("✅ <b>Данные приняты!</b>\nИщу прогноз...")
        try:
            birth_date = datetime.datetime.strptime(answers.get("birth_date"), "%d.%m.%Y").date()
            user_sign = get_zodiac_sign(birth_date)
            horoscope_text = await redis_service.get_horoscope(user_sign)
            
            if not horoscope_text:
                await callback.message.answer("✨ Гороскопы на сегодня еще формируются. Попробуйте через пару минут!")
            else:
                sign_name = RUS_SIGNS[user_sign]
                await callback.message.answer(f"🔮 <b>Гороскоп для знака {sign_name}:</b>\n\n{horoscope_text}")
        except Exception as e:
            print(f"Ошибка гороскопа: {e}")
            await callback.message.answer("Произошла ошибка при получении прогноза.")

    await show_main_menu(callback.message, "🏠 Главное меню:", user_id)
    await callback.answer()

# Хендлер для кнопки-пустышки
@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()