import json
import aio_pika
from src.config import settings

async def send_to_queue(queue_name: str, data: dict):
    """Отправляет JSON задачу в RabbitMQ"""
    connection = await aio_pika.connect_robust(settings.RABBIT_URL)
    
    async with connection:
        channel = await connection.channel()
        
        # Объявляем очередь (durable=True, чтобы задачи не пропали при перезагрузке)
        queue = await channel.declare_queue(queue_name, durable=True)
        
        message_body = json.dumps(data).encode()
        
        await channel.default_exchange.publish(
            aio_pika.Message(body=message_body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key=queue_name
        )