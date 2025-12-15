import json
import aio_pika
from src.config import settings

# --- OBSERVABILITY ---
from src.utils.logger import logger
from src.utils.alerting import send_alert
from src.utils.metrics import SYSTEM_ERRORS

async def send_to_queue(queue_name: str, data: dict):
    """
    Отправляет JSON задачу в RabbitMQ.
    Включает мониторинг ошибок и логирование.
    """
    # Создаем контекстный логгер
    log = logger.bind(service="rabbitmq", queue=queue_name)
    
    try:
        connection = await aio_pika.connect_robust(settings.RABBIT_URL)
        
        async with connection:
            channel = await connection.channel()
            
            # Объявляем очередь (durable=True)
            queue = await channel.declare_queue(queue_name, durable=True)
            
            message_body = json.dumps(data).encode()
            
            await channel.default_exchange.publish(
                aio_pika.Message(
                    body=message_body, 
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT
                ),
                routing_key=queue_name
            )
            
            # Логируем успех (на уровне debug, чтобы не спамить в проде, или info если важно)
            log.info("message_published_success", data_keys=list(data.keys()))

    except Exception as e:
        # Логируем ошибку
        log.error("message_publish_failed", error=str(e))
        
        # Фиксируем в метриках
        SYSTEM_ERRORS.labels(service="rabbitmq", error_type=type(e).__name__).inc()
        
        # Отправляем алерт, так как потеря связи с очередью — это критично
        await send_alert(e, context=f"RabbitMQ ({queue_name})")
        
        # Пробрасываем ошибку дальше, чтобы вызывающий код знал о провале
        raise e