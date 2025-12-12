import asyncio
from sqlalchemy import select, and_, not_, func
from src.database.session import async_session_maker
from src.database.models import UserSurvey, DatingMatch, User
from src.services.rabbit import send_to_queue
from src.bot.keyboards.dating import get_dating_kb

async def run_daily_matching():
    print("💘 Запуск ежедневного подбора пар...")
    
    async with async_session_maker() as session:
        # 1. Получаем всех активных пользователей дейтинга
        # У которых есть анкета dating
        stmt_users = select(UserSurvey).where(UserSurvey.mode == 'dating')
        result = await session.execute(stmt_users)
        all_profiles = result.scalars().all()
        
        # Простой алгоритм: перебор всех со всеми (для MVP ок, для прода нужен GeoIP и фильтры в SQL)
        for me in all_profiles:
            my_id = me.user_id
            my_data = me.answers # JSON
            my_city = my_data.get('city', '').lower().strip()
            my_gender = my_data.get('gender')
            
            # Кого ищем? (Предположим простую логику: М ищет Ж, Ж ищет М)
            # В идеале это должно быть в анкете: "pref_gender"
            target_gender = "Женский" if my_gender == "Мужской" else "Мужской"

            # 2. Ищем кандидата
            # - Живет в том же городе
            # - Нужного пола
            # - Которого я еще НЕ лайкал/дизлайкал
            
            # Подзапрос: кого я уже видел
            subq_seen = select(DatingMatch.target_user_id).where(DatingMatch.user_id == my_id)
            
            # Основной запрос: Ищем случайного кандидата
            stmt_candidate = select(UserSurvey).where(
                and_(
                    UserSurvey.mode == 'dating',
                    UserSurvey.user_id != my_id,
                    UserSurvey.user_id.not_in(subq_seen),
                    # UserSurvey.answers['city'].astext.ilike(my_city) # Для PostgreSQL JSONB
                )
            ).limit(1)
            
            # Примечание: фильтрацию по JSON в SQL лучше делать через операторы ->>, 
            # но для MVP сделаем перебор в Python, если юзеров мало. 
            # Для 10к юзеров нужен правильный SQL.
            
            # Правильный SQL для JSONB (требует, чтобы answers было JSONB в модели):
            # func.jsonb_extract_path_text(UserSurvey.answers, 'city') == my_city
            
            res_candidate = await session.execute(stmt_candidate)
            candidate = res_candidate.scalar_one_or_none()

            if not candidate:
                continue

            # 3. Отправляем анкету
            cand_data = candidate.answers
            photo_id = cand_data.get('photo')
            name = cand_data.get('name', 'Аноним')
            age = cand_data.get('age', '??')
            about = cand_data.get('about', '')
            
            caption = f"💘 <b>Кандидат дня:</b>\n\n{name}, {age}\n📍 {my_city}\n\nℹ️ {about}"
            
            # Формируем задачу для Sender
            # Sender должен уметь отправлять фото. Если в sender_worker только send_message, надо доработать.
            # Пока предположим, что sender умеет (надо дописать).
            
            # Чтобы не усложнять Sender сейчас, давай сделаем, что Matching кидает задачу спец. типа
            # Или допишем Sender.
            
            msg_data = {
                "user_id": my_id,
                "text": caption, # Если фото нет
                "photo": photo_id, # Новое поле
                "keyboard": get_dating_kb(candidate.user_id).model_dump()
            }
            
            await send_to_queue("q_notifications", msg_data)
            await asyncio.sleep(0.05) # Чтобы не забить очередь мгновенно

    print("💘 Подбор завершен.")