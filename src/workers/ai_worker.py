import asyncio
import json
import sys
import re
import aio_pika
from os.path import abspath, dirname

# Магия путей
sys.path.insert(0, dirname(dirname(dirname(abspath(__file__)))))

from src.config import settings
from src.services.llm import generate_response
from src.database.session import async_session_maker
from src.database.models import UserSurvey
from sqlalchemy import update
from src.services.redis import redis_service 
from src.services.rabbit import send_to_queue

# --- ФУНКЦИЯ ОЧИСТКИ И ФОРМАТИРОВАНИЯ HTML ---
def clean_html_for_telegram(text: str) -> str:
    """
    Превращает веб-HTML от ИИ в Telegram-HTML.
    """
    # 1. Убираем обертки Markdown кода
    text = re.sub(r'```html', '', text, flags=re.IGNORECASE)
    text = re.sub(r'```', '', text)

    # 2. Вырезаем служебные теги
    text = re.sub(r'<!DOCTYPE[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<html[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</html>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<head>.*?</head>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<body[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</body>', '', text, flags=re.IGNORECASE)

    # 3. СПИСКИ С ОТСТУПОМ
    # Удаляем ul/ol
    text = re.sub(r'<ul[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</ul>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<ol[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</ol>', '', text, flags=re.IGNORECASE)
    
    # <li> превращаем в: Перенос строки + 3 пробела + Точка
    # Это создаст эффект табуляции
    text = re.sub(r'<li[^>]*>', '\n   • ', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '', text, flags=re.IGNORECASE)

    # 4. Обработка параграфов
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<p[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<div[^>]*>', '', text, flags=re.IGNORECASE)

    # 5. Заголовки -> жирный
    text = re.sub(r'<h[1-6][^>]*>', '\n<b>', text, flags=re.IGNORECASE)
    text = re.sub(r'</h[1-6]>', '</b>\n', text, flags=re.IGNORECASE)

    # 6. Чистка мусора
    text = re.sub(r'<span[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</span>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n{3,}', '\n\n', text) # Убираем лишние пустые строки
    
    return text.strip()

async def process_task(message: aio_pika.IncomingMessage):
    async with message.process():
        task = json.loads(message.body)
        print(f"🤖 [AI Worker] Задача: {task['mode']} | User: {task['user_id']}")
        
        user_id = task['user_id']
        mode = task['mode']
        answers = task['answers']
        survey_db_id = task['survey_id']

        # 1. Получаем промпт
        prompt_template = await redis_service.get_prompt(mode)
        if not prompt_template:
            print(f"❌ Нет промпта для режима {mode}")
            return
        
        # 2. Подстановка переменных
        try:
            system_text = prompt_template.format(**answers)
        except Exception as e:
            print(f"⚠️ JSON injection: {e}")
            system_text = prompt_template + f"\n\nДанные: {json.dumps(answers, ensure_ascii=False)}"

        # 3. ОБНОВЛЕННАЯ ИНСТРУКЦИЯ ДЛЯ ИИ
        user_content = (
            "Составь рекомендацию на основе моих данных.\n"
            "ТРЕБОВАНИЯ К ОФОРМЛЕНИЮ:\n"
            "1. Эмодзи используй ТОЛЬКО в заголовках и очень умеренно (не более 1 на заголовок).\n"
            "2. Внутри списков (перечислениях) эмодзи НЕ ИСПОЛЬЗУЙ.\n"
            "3. Используй тег <b> для жирного выделения заголовков.\n"
            "4. Списки оформляй строго тегами <li>.\n"
            "5. Пиши сразу в HTML, не используй Markdown.\n"
            "6. НЕ пиши <!DOCTYPE> или <html>, только текст."
        )
        
        ai_result = await generate_response(system_text, user_content)
        
        # 4. Очистка и добавление отступов
        clean_result = clean_html_for_telegram(ai_result)
        
        # 5. Сборка сообщения
        final_text = (
            f"✅ <b>Ваши рекомендации ({mode}) готовы!</b>\n\n"
            f"<blockquote expandable>{clean_result}</blockquote>\n\n"
            "--- \n"
            "⚠️ <i><b>Важно:</b> Рекомендации носят информационный характер.</i>"
        )
        
        # 6. Сохраняем
        async with async_session_maker() as session:
            stmt = update(UserSurvey).where(UserSurvey.id == survey_db_id).values(ai_recommendation=clean_result)
            await session.execute(stmt)
            await session.commit()

        # 7. Отправка результата
        await send_to_queue("q_notifications", {
            "user_id": user_id,
            "text": final_text
        })
        
        # 8. Отправка предложения о трекинге
        tracking_keyboard = {
            "inline_keyboard": [[
                {"text": "👍 Да, давай!", "callback_data": "tracking_subscribe"},
                {"text": "👎 Нет, спасибо", "callback_data": "tracking_unsubscribe"}
            ]]
        }
        await asyncio.sleep(1)
        await send_to_queue("q_notifications", {
            "user_id": user_id,
            "text": "Хотите, чтобы я каждый день спрашивал о ваших успехах?",
            "keyboard": tracking_keyboard
        })

async def main():
    print("🚀 AI Worker (OpenAI Proxy) запущен...")
    connection = await aio_pika.connect_robust(settings.RABBIT_URL)
    channel = await connection.channel()
    queue = await channel.declare_queue("q_ai_generation", durable=True)
    await channel.set_qos(prefetch_count=5)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            asyncio.create_task(process_task(message))

if __name__ == "__main__":
    from src.services.redis import redis_service
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())