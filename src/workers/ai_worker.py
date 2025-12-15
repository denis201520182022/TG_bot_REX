import asyncio
import json
import sys
import re
import time  # <--- Для замера времени
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

# --- НОВЫЕ ИМПОРТЫ (OBSERVABILITY) ---
from src.utils.logger import logger
from src.utils.metrics import start_metrics_server, AI_TASK_PROCESSED, AI_TASK_DURATION
from src.utils.alerting import send_alert
from src.utils.text import clean_html_for_telegram

async def process_task(message: aio_pika.IncomingMessage):
    async with message.process():
        start_time = time.time()
        
        # 1. Парсинг задачи
        try:
            task = json.loads(message.body)
        except json.JSONDecodeError as e:
            # Если JSON битый, мы не можем даже узнать user_id, просто логируем ошибку и дропаем
            logger.error("json_decode_error", error=str(e), body=message.body.decode())
            return # Ack (подтверждаем), чтобы удалить битое сообщение из очереди

        user_id = task.get('user_id')
        mode = task.get('mode', 'unknown')
        answers = task.get('answers', {})
        survey_db_id = task.get('survey_id')

        # Привязываем контекст к логгеру (теперь все логи будут иметь эти поля)
        log = logger.bind(user_id=user_id, mode=mode, survey_id=survey_db_id, worker="ai_worker")
        log.info("task_started")

        try:
            # 2. Получаем шаблон промпта
            prompt_template = await redis_service.get_prompt(mode)
            if not prompt_template:
                log.error("prompt_missing_in_redis")
                # Тут можно отправить юзеру "Извините, сервис недоступен", но пока просто выходим
                return
            
            # 3. Подстановка переменных
            try:
                system_text = prompt_template.format(**answers)
            except Exception as e:
                log.warning("prompt_format_warning", error=str(e), hint="Using JSON injection")
                system_text = prompt_template + f"\n\nДанные: {json.dumps(answers, ensure_ascii=False)}"

            # 4. Инструкция для ИИ
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
            
            # 5. Запрос к LLM (Замеряем время)
            log.info("llm_request_started")
            llm_start = time.time()
            
            ai_result = await generate_response(system_text, user_content)
            
            llm_duration = time.time() - llm_start
            AI_TASK_DURATION.labels(mode=mode).observe(llm_duration) # Метрика времени
            log.info("llm_request_completed", duration=llm_duration)

            # 6. Очистка
            clean_result = clean_html_for_telegram(ai_result)
            
            final_text = (
                f"✅ <b>Ваши рекомендации ({mode}) готовы!</b>\n\n"
                f"<blockquote expandable>{clean_result}</blockquote>\n\n"
                "--- \n"
                "⚠️ <i><b>Важно:</b> Рекомендации носят информационный характер.</i>"
            )
            
            # 7. Сохраняем в БД
            async with async_session_maker() as session:
                stmt = update(UserSurvey).where(UserSurvey.id == survey_db_id).values(ai_recommendation=clean_result)
                await session.execute(stmt)
                await session.commit()

            # 8. Отправляем в очередь уведомлений
            await send_to_queue("q_notifications", {
                "user_id": user_id,
                "text": final_text
            })
            
            # Обновляем метрику успеха
            AI_TASK_PROCESSED.labels(mode=mode, status="success").inc()
            log.info("task_completed_successfully", total_duration=time.time() - start_time)

        except Exception as e:
            # Обработка критических ошибок
            log.error("task_failed", error=str(e))
            
            # Метрика ошибки
            AI_TASK_PROCESSED.labels(mode=mode, status="error").inc()
            
            # Алерт админу
            await send_alert(e, context=f"AI Worker ({mode})")
            
            # ВАЖНО: Если мы здесь, значит aio_pika не сделает ack автоматически, 
            # так как исключение было перехвачено.
            # Если мы хотим, чтобы задача вернулась в очередь и попробовала снова (retry), нужно:
            # raise e 
            # Но если ошибка логическая (баг в коде), бесконечный ретрай убьет логи.
            # Пока что мы просто логируем и считаем задачу "обработанной с ошибкой" (Ack).
            pass 

async def main():
    logger.info("service_started", service="ai_worker")
    
    # Подключение к RabbitMQ
    connection = await aio_pika.connect_robust(settings.RABBIT_URL)
    channel = await connection.channel()
    queue = await channel.declare_queue("q_ai_generation", durable=True)
    await channel.set_qos(prefetch_count=5)

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            asyncio.create_task(process_task(message))

if __name__ == "__main__":
    from src.services.redis import redis_service
    
    # Запуск сервера метрик на порту 8000
    start_metrics_server(8000)
    
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("service_stopped")