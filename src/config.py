from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

class Settings(BaseSettings):
    # Telegram
    BOT_TOKEN: SecretStr
    ADMIN_IDS: str  # Придет строкой "123,456", распарсим потом

    # Database
    DB_URL: str  # postgresql+asyncpg://...

    # Redis & Rabbit
    REDIS_URL: str
    RABBIT_URL: str

    # External APIs
    QWEN_API_KEY: SecretStr
    GOOGLE_CREDENTIALS_FILE: str
    GOOGLE_SHEET_ID: str

    # OpenAI & Proxy
    OPENAI_API_KEY: SecretStr
    SQUID_PROXY_HOST: str
    SQUID_PROXY_PORT: str
    SQUID_PROXY_USER: str
    SQUID_PROXY_PASSWORD: str

    # Читаем из файла .env
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

# Создаем экземпляр настроек, который будем импортировать везде
settings = Settings()