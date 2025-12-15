import json
import datetime
import asyncio
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, 
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.enums import ContentType
from sqlalchemy import select
from src.config import settings

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

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def is_admin(user_id: int) -> bool:
    try:
        admin_ids = [int(x) for x in settings.ADMIN_IDS.split(',')]
        return user_id in admin_ids
    except:
        return False

async def show_main_menu(message: Message, text: str, user_id: int):
    credits = 0
    # Админу рисуем 999 для красоты
    if is_admin(user_id):
        credits = 999
    else:
        async with async_session_maker() as session:
            user = await session.get(User, user_id)
            if user: credits = user.natal_chart_credits
            
    await message.answer(text, reply_markup=get_main_menu(natal_credits=credits, is_admin=is_admin(user_id)))

def get_options_keyboard(options: list) -> ReplyKeyboardMarkup:
    """Генерирует клавиатуру с вариантами ответов."""
    keyboard = []
    row = []
    for opt in options:
        row.append(KeyboardButton(text=opt))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([KeyboardButton(text="❌ Отмена")])
    
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите вариант 👇"
    )

# --- ХЕНДЛЕР СПРАВКИ ---

@router.message(F.text.contains("Справка"))
async def show_help(message: Message):
    help_text = (
        "🤖 <b>Как пользоваться ботом REX:</b>\n\n"
        "1. <b>Выберите режим</b> в меню внизу.\n"
        "2. <b>Ответьте на вопросы</b> анкеты.\n"
        "3. <b>Получите результат:</b>\n"
        "   — 🥦/💪 План питания или тренировок.\n"
        "   — 🔮 Гороскоп на сегодня.\n"
        "   — ❤️ Поиск партнера.\n\n"
        "📅 <b>Ежедневный трекинг:</b>\n"
        "Мы будем спрашивать о ваших успехах в 20:00.\n"
        "Включить/выключить его можно в меню Диетолога или Тренера."
    )
    await message.answer(help_text)

# --- ПРОМЕЖУТОЧНОЕ МЕНЮ ---

def get_mode_menu_kb(mode: str, is_tracking_on: bool) -> InlineKeyboardMarkup:
    tracking_text = "✅ Трекинг ВКЛ" if is_tracking_on else "❌ Трекинг ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Заполнить/обновить анкету", callback_data=f"start_survey_{mode}")],
        [InlineKeyboardButton(text=tracking_text, callback_data=f"toggle_tracking_{mode}")]
    ])

@router.message(F.text.in_(["🥦 Диетолог", "💪 Тренер"]))
async def show_mode_menu(message: Message):
    mode = MENU_MAPPING[message.text]
    async with async_session_maker() as session:
        user = await session.get(User, message.from_user.id)
        if not user: return 
        is_tracking = user.is_diet_tracking if mode == 'diet' else user.is_trainer_tracking
    
    await message.answer(
        f"Вы выбрали режим <b>{mode.capitalize()}</b>. Что делаем?",
        reply_markup=get_mode_menu_kb(mode, is_tracking)
    )

@router.callback_query(F.data.startswith("toggle_tracking_"))
async def toggle_tracking(callback: CallbackQuery):
    mode = callback.data.split("_")[2]
    new_status = False 
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
    await callback.answer(f"Трекинг {'включен' if new_status else 'выключен'}")

# --- ЗАПУСК АНКЕТЫ ---

# 1. НАТАЛЬНАЯ КАРТА
@router.message(F.text.contains("Натальная карта"))
async def start_natal_chart(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Проверка для АДМИНА
    if is_admin(user_id):
        # Админ проходит без проверки кредитов
        pass
    else:
        # Обычный юзер
        async with async_session_maker() as session:
            user = await session.get(User, user_id)
            if user.natal_chart_credits < 1:
                return await message.answer("❌ У вас нет попыток. Активируйте больше QR-кодов!")
            
    await _start_survey_logic(message, state, "natal_chart")

# 2. ГОРОСКОП (Проверка на 1 раз в день)
@router.message(F.text.contains("Астро-прогноз"))
async def start_horoscope(message: Message, state: FSMContext):
    user_id = message.from_user.id
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    # Проверяем Redis ключ: horoscope_viewed:USER_ID:DATE
    viewed = await redis_service.get(f"horoscope_viewed:{user_id}:{today_str}")
    
    # Если уже смотрел и НЕ админ (админу можно тестить)
    if viewed and not is_admin(user_id):
        return await message.answer("🔮 Звезды говорят только раз в день. Приходите завтра!")
        
    await _start_survey_logic(message, state, "horoscope")

# 3. ОСТАЛЬНЫЕ (Дейтинг)
@router.message(F.text.in_(["❤️ Найти партнера"]))
async def start_survey_by_text(message: Message, state: FSMContext):
    mode = MENU_MAPPING[message.text]
    await _start_survey_logic(message, state, mode)

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
    kb = None
    if first_q['type'] == 'button' and first_q.get('options'):
        kb = get_options_keyboard(first_q['options'])
    else:
        kb = get_cancel_kb()

    await message.answer(
        f"📝 <b>Режим: {mode.upper()}</b>\n\nВопрос 1/{len(questions)}:\n{first_q['text']}", 
        reply_markup=kb
    )

# --- ОТМЕНА ---

@router.callback_query(F.data == "cancel_survey", SurveyState.in_progress)
async def cancel_survey_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Анкета прервана.")
    await show_main_menu(callback.message, "Выберите режим:", callback.from_user.id)

@router.message(F.text == "❌ Отмена", SurveyState.in_progress)
async def cancel_survey_text(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Анкета прервана.", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(message, "Выберите режим:", message.from_user.id)

# --- ПОШАГОВАЯ ОБРАБОТКА ВОПРОСОВ ---

@router.message(SurveyState.in_progress, F.content_type.in_([ContentType.TEXT, ContentType.PHOTO]))
async def process_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    mode, step, answers = data['survey_mode'], data['current_step'], data['answers']
    
    questions = await redis_service.get_survey_config(mode)
    if not questions:
        await message.answer("Ошибка конфигурации. Попробуйте позже.")
        await state.clear()
        return

    current_q = questions[step]
    answer_value = None

    if current_q['type'] == 'photo':
        if not message.photo: 
            return await message.answer("📸 Пожалуйста, отправьте фотографию (не файлом).")
        answer_value = message.photo[-1].file_id
    else: 
        if not message.text: 
            return await message.answer("✍️ Пожалуйста, введите текстовый ответ.")
        user_text = message.text.strip()
        if current_q['key'] == 'birth_date':
            try:
                datetime.datetime.strptime(user_text, "%d.%m.%Y").date()
            except ValueError:
                return await message.answer("❗️Неверный формат. Введите дату как ДД.ММ.ГГГГ")
        answer_value = user_text

    answers[current_q['key']] = answer_value
    next_step = step + 1

    if next_step < len(questions):
        await state.update_data(current_step=next_step, answers=answers)
        next_q = questions[next_step]
        
        kb = None
        if next_q['type'] == 'button' and next_q.get('options'):
            kb = get_options_keyboard(next_q['options'])
        else:
            kb = get_cancel_kb()

        await message.answer(
            f"Вопрос {next_step + 1}/{len(questions)}:\n{next_q['text']}", 
            reply_markup=kb
        )
    else:
        await state.update_data(answers=answers)
        await state.set_state(SurveyState.final_consent)
        
        consent_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Согласен(а)", callback_data="consent_yes")],
            [InlineKeyboardButton(text="❌ Отказаться", callback_data="consent_no")]
        ])
        
        await message.answer("...", reply_markup=ReplyKeyboardRemove()) 
        await message.answer(
            "📄 <b>Согласие на обработку данных:</b>\n\n"
            "Нажимая кнопку «Согласен(а)», вы подтверждаете свое согласие на обработку персональных данных.",
            reply_markup=consent_kb
        )

# --- ОБРАБОТКА СОГЛАСИЯ (ФИНАЛ) ---

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
        user = await session.get(User, user_id)
        
        # --- СПИСАНИЕ КРЕДИТА (НАТАЛЬНАЯ КАРТА) ---
        if mode == 'natal_chart':
            if not is_admin(user_id): # Админу бесплатно
                if user.natal_chart_credits > 0:
                    user.natal_chart_credits -= 1
                else:
                    await callback.answer("Ошибка: нет кредитов.", show_alert=True)
                    return await show_main_menu(callback.message, "🏠 Главное меню:", user_id)
        # ------------------------------------------

        is_tracking_enabled = False
        if mode == 'diet': is_tracking_enabled = user.is_diet_tracking
        elif mode == 'trainer': is_tracking_enabled = user.is_trainer_tracking

        config_map = {'diet': 1, 'trainer': 2, 'dating': 3, 'horoscope': 4, 'natal_chart': 5}
        config_id = config_map.get(mode, 1)

        new_survey = UserSurvey(user_id=user_id, mode=mode, survey_config_id=config_id, answers=answers)
        session.add(new_survey)
        await session.flush()
        new_survey_id = new_survey.id
        await session.commit()
    
    # --- ЛОГИКА ПОСЛЕ АНКЕТЫ ---
    if mode in ['diet', 'trainer', 'natal_chart']:
        await callback.message.answer(f"✅ <b>Принято!</b>\nОбрабатываем... ⏳")
        task_data = {"user_id": user_id, "mode": mode, "answers": answers, "survey_id": new_survey_id}
        await send_to_queue("q_ai_generation", task_data)
        
        if mode in ['diet', 'trainer'] and not is_tracking_enabled:
            tracking_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="👍 Да, хочу!", callback_data=f"toggle_tracking_{mode}"),
                InlineKeyboardButton(text="👎 Не сейчас", callback_data="ignore")
            ]])
            await asyncio.sleep(1) 
            await callback.message.answer(
                "Хотите, чтобы я каждый день в 20:00 спрашивал о ваших успехах в этом режиме?",
                reply_markup=tracking_kb
            )
            
    elif mode == 'dating':
        await callback.message.answer("✅ <b>Анкета знакомств сохранена!</b>\nЖдите предложений в 12:00.")
        
    elif mode == 'horoscope':
        # ФИКС: Записываем, что юзер получил гороскоп на сегодня
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        await redis_service.set(f"horoscope_viewed:{user_id}:{today_str}", "1", ex=86400)
        
        await callback.message.answer("✅ <b>Данные приняты!</b>\nСоставляем прогноз...")
        try:
            birth_date = datetime.datetime.strptime(answers.get("birth_date"), "%d.%m.%Y").date()
            user_sign = get_zodiac_sign(birth_date)
            horoscope_text = await redis_service.get_horoscope(user_sign)
            
            if not horoscope_text:
                await callback.message.answer("✨ Гороскопы формируются. Попробуйте через пару минут!")
            else:
                sign_name = RUS_SIGNS[user_sign]
                await callback.message.answer(f"🔮 <b>Гороскоп для знака {sign_name}:</b>\n\n{horoscope_text}")
        except Exception as e:
            print(f"Ошибка гороскопа: {e}")
            await callback.message.answer("Ошибка даты.")

    await show_main_menu(callback.message, "🏠 Главное меню:", user_id)
    await callback.answer()

@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    try: await callback.message.delete()
    except: pass
    await callback.answer()