import datetime
from sqlalchemy import BigInteger, String, Boolean, DateTime, ForeignKey, Integer, JSON, Text, Date
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.sql import func

# Базовый класс для всех моделей
class Base(AsyncAttrs, DeclarativeBase):
    pass

# 1. Пользователи
class User(Base):
    __tablename__ = 'users'

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram ID
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    # Роль и доступ
    role: Mapped[str] = mapped_column(String(20), default='user')
    subscription_expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Геймификация и доступы
    qr_activations_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    natal_chart_credits: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    
    # --- ТРЕКИНГ (РАЗДЕЛЬНЫЙ) ---
    is_diet_tracking: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_trainer_tracking: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    has_accepted_policy: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # ----------------------------

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    
    # Связи
    surveys: Mapped[list["UserSurvey"]] = relationship(back_populates="user")
    qr_activation: Mapped["QRCode"] = relationship(back_populates="activated_by_user", uselist=False)

# 2. QR Коды
class QRCode(Base):
    __tablename__ = 'qr_codes'

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True) # Уникальный хэш
    batch_id: Mapped[str] = mapped_column(String(50)) # Номер партии
    is_active: Mapped[bool] = mapped_column(Boolean, default=True) # Глобальный рубильник
    
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    
    activated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_by_id: Mapped[int | None] = mapped_column(ForeignKey('users.user_id'), nullable=True)
    
    activated_by_user: Mapped["User"] = relationship(back_populates="qr_activation")

# 3. Конфигурация анкет (Версионирование)
class SurveyConfig(Base):
    __tablename__ = 'survey_configs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(20)) # 'diet', 'fitness', 'dating'
    version: Mapped[str] = mapped_column(String(50)) # хэш версии
    
    # Структура вопросов JSON: [{"q": "Вес?", "type": "int"}, ...]
    structure: Mapped[dict] = mapped_column(JSON) 
    
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

# 4. Ответы пользователей
class UserSurvey(Base):
    __tablename__ = 'user_surveys'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.user_id'))
    
    mode: Mapped[str] = mapped_column(String(20))
    survey_config_id: Mapped[int] = mapped_column(ForeignKey('survey_configs.id'))
    
    # Ответы: {"weight": 80, "goal": "loss"}
    answers: Mapped[dict] = mapped_column(JSON)
    
    # Результат от AI
    ai_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    
    user: Mapped["User"] = relationship(back_populates="surveys")

# 5. Дейтинг (Мэтчи)
class DatingMatch(Base):
    __tablename__ = 'dating_matches'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    user_id: Mapped[int] = mapped_column(ForeignKey('users.user_id')) # Кто лайкнул
    target_user_id: Mapped[int] = mapped_column(BigInteger) # Кого лайкнул
    
    action: Mapped[str] = mapped_column(String(10)) # 'like', 'dislike'
    is_match: Mapped[bool] = mapped_column(Boolean, default=False)
    
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

# 6. Ежедневный трекинг
class DailyTracking(Base):
    __tablename__ = 'daily_tracking'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.user_id'))
    
    # Режим ('diet' или 'trainer')
    mode: Mapped[str] = mapped_column(String(20), default="diet", server_default="diet") 

    # ТУТ Я ПОМЕНЯЛ DateTime на Date для строгости
    date: Mapped[datetime.date] = mapped_column(Date, default=func.current_date())
    status: Mapped[str] = mapped_column(String(20)) # 'success', 'partial', 'fail'
    
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())