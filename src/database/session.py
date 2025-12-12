from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.config import settings
from sqlalchemy.ext.asyncio import AsyncSession

# Создаем асинхронный движок
# echo=True будет выводить все SQL запросы в консоль (удобно для отладки, на проде выключим)
engine = create_async_engine(
    settings.DB_URL,
    echo=False, 
    pool_size=20,     # Держим 20 соединений
    max_overflow=10   # В пике до 30
)

# Фабрика сессий - ее мы будем использовать в коде
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Функция для получения сессии (Dependency Injection style)
async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session