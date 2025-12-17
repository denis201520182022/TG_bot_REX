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
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, update
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

async def _get_menu_markup(user_id: int) -> ReplyKeyboardMarkup:
    """Генерирует объект клавиатуры главного меню."""
    credits = 0
    if is_admin(user_id):
        credits = 999
    else:
        async with async_session_maker() as session:
            user = await session.get(User, user_id)
            if user: credits = user.natal_chart_credits
            
    return get_main_menu(natal_credits=credits, is_admin=is_admin(user_id))

async def safe_delete(bot, chat_id, message_id):
    try: await bot.delete_message(chat_id, message_id)
    except Exception: pass

def get_options_keyboard_inline(options: list) -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for opt in options:
        cb_data = f"ans_{opt}"[:64]
        row.append(InlineKeyboardButton(text=opt, callback_data=cb_data))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    # Кнопку отмены отсюда убрали, она теперь в Reply (снизу)
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# --- ХЕНДЛЕРЫ МЕНЮ И СПРАВКИ ---

@router.message(F.text.contains("Справка"))
async def show_help(message: Message):
    await safe_delete(message.bot, message.chat.id, message.message_id)
    help_text = (
        "🤖 <b>Как пользоваться ботом REX:</b>\n\n"
        "1. <b>Выберите режим</b> в меню внизу.\n"
        "2. <b>Ответьте на вопросы</b> анкеты.\n"
        "3. <b>Получите результат:</b>\n"
        "   — 🥦/💪 План питания или тренировок.\n"
        "   — 🔮 Гороскоп на сегодня.\n"
        "   — ❤️ Поиск партнера.\n\n"
        "📅 <b>Ежедневный трекинг:</b>\n"
        "Мы будем спрашивать о ваших успехах в 20:00."
    )
    await message.answer(help_text)

def get_mode_menu_kb(mode: str, is_tracking_on: bool) -> InlineKeyboardMarkup:
    tracking_text = "✅ Трекинг ВКЛ" if is_tracking_on else "❌ Трекинг ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Заполнить/обновить анкету", callback_data=f"start_survey_{mode}")],
        [InlineKeyboardButton(text=tracking_text, callback_data=f"toggle_tracking_{mode}")]
    ])

@router.message(F.text.in_(["🥦 Диетолог", "💪 Тренер"]))
async def show_mode_menu(message: Message):
    await safe_delete(message.bot, message.chat.id, message.message_id)
    mode = MENU_MAPPING[message.text]
    async with async_session_maker() as session:
        user = await session.get(User, message.from_user.id)
        if not user: return 
        is_tracking = user.is_diet_tracking if mode == 'diet' else user.is_trainer_tracking
    
    await message.answer(
        f"Режим <b>{mode.capitalize()}</b>. Настройки:",
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

@router.message(F.text.contains("Натальная карта"))
async def start_natal_chart(message: Message, state: FSMContext):
    await safe_delete(message.bot, message.chat.id, message.message_id)
    user_id = message.from_user.id
    if not is_admin(user_id):
        async with async_session_maker() as session:
            user = await session.get(User, user_id)
            if user.natal_chart_credits < 1:
                await message.answer("❌ Нет попыток. Активируйте больше QR-кодов!")
                return
    await _start_survey_logic(message, state, "natal_chart")

@router.message(F.text.contains("Астро-прогноз"))
async def start_horoscope(message: Message, state: FSMContext):
    await safe_delete(message.bot, message.chat.id, message.message_id)
    user_id = message.from_user.id
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    viewed = await redis_service.get(f"horoscope_viewed:{user_id}:{today_str}")
    
    if viewed and not is_admin(user_id):
        return await message.answer("🔮 Только один прогноз в день!")
        
    await _start_survey_logic(message, state, "horoscope")

@router.message(F.text.in_(["❤️ Найти партнера"]))
async def start_survey_by_text(message: Message, state: FSMContext):
    await safe_delete(message.bot, message.chat.id, message.message_id)
    mode = MENU_MAPPING[message.text]
    await _start_survey_logic(message, state, mode)

@router.callback_query(F.data.startswith(("mode_", "start_survey_")))
async def start_survey_by_callback(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split("_")[-1]
    # Удаляем меню выбора перед стартом анкеты
    await safe_delete(callback.message.bot, callback.message.chat.id, callback.message.message_id)
    await _start_survey_logic(callback.message, state, mode)
    await callback.answer()

# === ЛОГИКА ЗАПУСКА (ИСПРАВЛЕНАЯ) ===

async def _start_survey_logic(message: Message, state: FSMContext, mode: str):
    questions = await redis_service.get_survey_config(mode)
    if not questions:
        return await message.answer("⚠️ Режим не настроен.")

    await state.set_state(SurveyState.in_progress)
    await state.update_data(survey_mode=mode, current_step=0, answers={})
    
    first_q = questions[0]
    
    # 1. Отправляем Reply клавиатуру "Назад" и СОХРАНЯЕМ это сообщение
    # (Мы его не удаляем, чтобы кнопка висела!)
    back_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="↩️ Назад")]],
        resize_keyboard=True,
        persistent=True # Важно: помогает кнопке не прятаться
    )
    
    # Отправляем сообщение-заголовок, которое держит клавиатуру
    header_msg = await message.answer(f"🚀 <b>Режим: {mode.upper()}</b>", reply_markup=back_kb)
    
    # Сохраняем ID хедера, чтобы потом его удалить
    await state.update_data(survey_header_id=header_msg.message_id)

    # 2. Формируем Inline клавиатуру для вопроса
    kb = None
    if first_q['type'] == 'button' and first_q.get('options'):
        kb = get_options_keyboard_inline(first_q['options'])
    
    # 3. Отправляем первый вопрос
    sent_msg = await message.answer(
        f"Вопрос 1/{len(questions)}:\n{first_q['text']}", 
        reply_markup=kb
    )
    await state.update_data(last_bot_message_id=sent_msg.message_id)

# --- ОТМЕНА ---

@router.callback_query(F.data == "cancel_survey", SurveyState.in_progress)
async def cancel_survey_callback(callback: CallbackQuery, state: FSMContext):
    await _cleanup_survey(callback.message, state)
    menu = await _get_menu_markup(callback.from_user.id)
    await callback.message.answer("", reply_markup=menu)

@router.message(F.text == "↩️ Назад", SurveyState.in_progress)
async def cancel_survey_text(message: Message, state: FSMContext):
    # Удаляем само сообщение "Назад"
    await safe_delete(message.bot, message.chat.id, message.message_id)
    
    await _cleanup_survey(message, state)
    
    menu = await _get_menu_markup(message.from_user.id)
    await message.answer("🏠 Главное меню", reply_markup=menu)

async def _cleanup_survey(message: Message, state: FSMContext):
    """Удаляет вопросы и хедер с кнопкой Назад."""
    data = await state.get_data()
    last_id = data.get('last_bot_message_id')
    header_id = data.get('survey_header_id')
    
    if last_id: await safe_delete(message.bot, message.chat.id, last_id)
    if header_id: await safe_delete(message.bot, message.chat.id, header_id)
    
    await state.clear()

# --- ПОШАГОВАЯ ОБРАБОТКА ВОПРОСОВ ---

@router.callback_query(F.data.startswith("ans_"), SurveyState.in_progress)
async def process_button_answer(callback: CallbackQuery, state: FSMContext):
    answer = callback.data[4:] 
    await _handle_answer(callback.message, state, answer_value=answer, is_edit=True)
    await callback.answer()

@router.message(SurveyState.in_progress, F.content_type.in_([ContentType.TEXT, ContentType.PHOTO]))
async def process_message_answer(message: Message, state: FSMContext):
    # Удаляем ответ юзера
    await safe_delete(message.bot, message.chat.id, message.message_id)
    
    data = await state.get_data()
    mode = data['survey_mode']
    step = data['current_step']
    questions = await redis_service.get_survey_config(mode)
    if not questions: return

    current_q = questions[step]
    val = None
    error_msg = None
    
    if current_q['type'] == 'photo':
        if not message.photo: error_msg = "📸 Нужно прислать ФОТО!"
        else: val = message.photo[-1].file_id
    else:
        if not message.text: error_msg = "✍️ Нужно прислать ТЕКСТ!"
        else:
            val = message.text.strip()
            if current_q['key'] == 'birth_date':
                try: datetime.datetime.strptime(val, "%d.%m.%Y").date()
                except ValueError: error_msg = "❗️ Неверный формат даты! (ДД.ММ.ГГГГ)"
    
    if error_msg:
        last_id = data.get('last_bot_message_id')
        if last_id:
            try:
                await message.bot.edit_message_text(
                    text=f"❗️ <b>{error_msg}</b>\n\n{current_q['text']}",
                    chat_id=message.chat.id,
                    message_id=last_id,
                    reply_markup=get_cancel_kb() # Тут можно оставить Inline Отмену как опцию
                )
            except: pass
        return

    await _handle_answer(message, state, answer_value=val, is_edit=True)

async def _handle_answer(message: Message, state: FSMContext, answer_value, is_edit: bool):
    data = await state.get_data()
    mode, step, answers = data['survey_mode'], data['current_step'], data['answers']
    last_bot_msg_id = data.get('last_bot_message_id')
    
    questions = await redis_service.get_survey_config(mode)
    current_q = questions[step]
    
    answers[current_q['key']] = answer_value
    next_step = step + 1

    if next_step < len(questions):
        await state.update_data(current_step=next_step, answers=answers)
        next_q = questions[next_step]
        
        kb = None
        if next_q['type'] == 'button' and next_q.get('options'):
            kb = get_options_keyboard_inline(next_q['options'])
        
        text = f"Вопрос {next_step + 1}/{len(questions)}:\n{next_q['text']}"
        
        if is_edit and last_bot_msg_id:
            try:
                await message.bot.edit_message_text(
                    text=text, chat_id=message.chat.id, message_id=last_bot_msg_id, reply_markup=kb
                )
            except TelegramBadRequest:
                await safe_delete(message.bot, message.chat.id, last_bot_msg_id)
                sent = await message.answer(text, reply_markup=kb)
                await state.update_data(last_bot_message_id=sent.message_id)
        else:
            sent = await message.answer(text, reply_markup=kb)
            await state.update_data(last_bot_message_id=sent.message_id)

    else:
        # ВОПРОСЫ ЗАКОНЧИЛИСЬ
        await state.update_data(answers=answers)
        
        # Проверка согласия (если уже было - пропускаем)
        user_id = message.chat.id
        async with async_session_maker() as session:
            user = await session.get(User, user_id)
            has_accepted = user.has_accepted_policy if user else False
            
        if has_accepted:
            # Сразу финиш
            await _finish_survey(message, state, user_id, mode, answers)
        else:
            await state.set_state(SurveyState.final_consent)
            # Удаляем последний вопрос
            if last_bot_msg_id: await safe_delete(message.bot, message.chat.id, last_bot_msg_id)

            consent_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Согласен(а)", callback_data="consent_yes")],
                [InlineKeyboardButton(text="❌ Отказаться", callback_data="consent_no")]
            ])
            
            await message.answer(
                "📄 <b>Согласие на обработку данных:</b>\n\nНажимая кнопку «Согласен(а)», вы подтверждаете свое согласие.",
                reply_markup=consent_kb
            )

# --- ОБРАБОТКА СОГЛАСИЯ ---

@router.callback_query(SurveyState.final_consent, F.data.in_(["consent_yes", "consent_no"]))
async def process_consent(callback: CallbackQuery, state: FSMContext):
    await safe_delete(callback.bot, callback.message.chat.id, callback.message.message_id)
    user_id = callback.from_user.id
    
    if callback.data == "consent_no":
        await _cleanup_survey(callback.message, state)
        menu = await _get_menu_markup(user_id)
        return await callback.message.answer("❌ Анкета отменена.", reply_markup=menu)

    # Записываем согласие
    async with async_session_maker() as session:
        stmt = update(User).where(User.user_id == user_id).values(has_accepted_policy=True)
        await session.execute(stmt)
        await session.commit()

    data = await state.get_data()
    mode, answers = data['survey_mode'], data['answers']
    
    await _finish_survey(callback.message, state, user_id, mode, answers)

# --- ФИНАЛИЗАЦИЯ (ОБЩАЯ) ---

async def _finish_survey(message: Message, state: FSMContext, user_id: int, mode: str, answers: dict):
    # Чистим чат (хедер с кнопкой Назад)
    await _cleanup_survey(message, state)
    
    # Меню для возврата
    menu = await _get_menu_markup(user_id)
    
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        
        # Кредиты
        if mode == 'natal_chart' and not is_admin(user_id):
            if user.natal_chart_credits > 0:
                user.natal_chart_credits -= 1
            else:
                return await message.answer("❌ Нет кредитов.", reply_markup=menu)

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
    
    # Логика по режимам
    if mode in ['diet', 'trainer', 'natal_chart']:
        await message.answer(f"✅ <b>Принято!</b>\nДанные обрабатываются... ⏳", reply_markup=menu)
        
        task_data = {"user_id": user_id, "mode": mode, "answers": answers, "survey_id": new_survey_id}
        await send_to_queue("q_ai_generation", task_data)
        
        if mode in ['diet', 'trainer'] and not is_tracking_enabled:
            tracking_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="👍 Да, хочу!", callback_data=f"toggle_tracking_{mode}"),
                InlineKeyboardButton(text="👎 Не сейчас", callback_data="ignore")
            ]])
            await asyncio.sleep(0.5) 
            await message.answer("Включить ежедневный трекинг (20:00)?", reply_markup=tracking_kb)
            
    elif mode == 'dating':
        await message.answer("✅ <b>Анкета сохранена!</b>\nЖдите предложений в 12:00.", reply_markup=menu)
        
    elif mode == 'horoscope':
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        await redis_service.set(f"horoscope_viewed:{user_id}:{today_str}", "1", ex=86400)
        
        try:
            birth_date = datetime.datetime.strptime(answers.get("birth_date"), "%d.%m.%Y").date()
            user_sign = get_zodiac_sign(birth_date)
            horoscope_text = await redis_service.get_horoscope(user_sign)
            
            if horoscope_text:
                sign_name = RUS_SIGNS[user_sign]
                await message.answer(f"🔮 <b>Гороскоп ({sign_name}):</b>\n\n{horoscope_text}", reply_markup=menu)
            else:
                await message.answer("✨ Гороскопы формируются.", reply_markup=menu)
        except Exception:
            await message.answer("Ошибка даты.", reply_markup=menu)

@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    await safe_delete(callback.bot, callback.message.chat.id, callback.message.message_id)
    await callback.answer()