import asyncio
import sys
from os.path import abspath, dirname

# Магия путей
sys.path.insert(0, dirname(dirname(dirname(abspath(__file__)))))

from sqlalchemy import select
from src.database.session import async_session_maker
from src.database.models import SurveyConfig
from src.bot.survey_config import SURVEYS

async def init_configs():
    print("⚙️ Проверка начальных конфигураций...")
    
    async with async_session_maker() as session:
        # 1. Проверяем, есть ли конфиг с ID=1
        stmt = select(SurveyConfig).where(SurveyConfig.id == 1)
        result = await session.execute(stmt)
        if result.scalar_one_or_none():
            print("✅ Конфигурации уже существуют. Пропуск.")
            return

        # 2. Если нет, создаем
        print("📥 Создаю базовые конфигурации в БД...")
        
        # Диетолог (ID 1)
        conf_diet = SurveyConfig(
            id=1,
            mode='diet',
            version='v1_init',
            structure=SURVEYS['diet'], # Берем из нашего файла
            is_current=True
        )
        
        # Тренер (ID 2)
        conf_trainer = SurveyConfig(
            id=2,
            mode='trainer',
            version='v1_init',
            structure=SURVEYS['trainer'],
            is_current=True
        )
        
        # Дейтинг (ID 3)
        conf_dating = SurveyConfig(
            id=3,
            mode='dating',
            version='v1_init',
            structure=SURVEYS['dating'],
            is_current=True
        )

        session.add_all([conf_diet, conf_trainer, conf_dating])
        await session.commit()
        print("💾 Конфигурации успешно сохранены (ID 1, 2, 3)!")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(init_configs())