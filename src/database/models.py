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
    
    # --- ТРЕКИНГ (РАЗДЕЛЬНЫЙ) ---
    # Мы убрали старый is_tracking_enabled и добавили два новых
    is_diet_tracking: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_trainer_tracking: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # ----------------------------

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    
    # Связи
    surveys: Mapped[list["UserSurvey"]] = relationship(back_populates="user")
    qr_activation: Mapped["QRCode"] = relationship(back_populates="activated_by_user", uselist=False)

# 2. QR Коды
class QRCode(Base):
    __tablename__ = 'qr_codes'

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    
    activated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_by_id: Mapped[int | None] = mapped_column(ForeignKey('users.user_id'), nullable=True)
    
    activated_by_user: Mapped["User"] = relationship(back_populates="qr_activation")

# 3. Конфигурация анкет
class SurveyConfig(Base):
    __tablename__ = 'survey_configs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(20))
    version: Mapped[str] = mapped_column(String(50))
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
    answers: Mapped[dict] = mapped_column(JSON)
    ai_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    
    user: Mapped["User"] = relationship(back_populates="surveys")

# 5. Дейтинг (Мэтчи)
class DatingMatch(Base):
    __tablename__ = 'dating_matches'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.user_id'))
    target_user_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(10))
    is_match: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

# 6. Ежедневный трекинг (Обновленный)
class DailyTracking(Base):
    __tablename__ = 'daily_tracking'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.user_id'))
    
    # --- НОВОЕ ПОЛЕ ---
    mode: Mapped[str] = mapped_column(String(20), default="diet", server_default="diet") 
    # 'diet' или 'trainer' - чтобы считать стрики раздельно
    # ------------------

    date: Mapped[datetime.date] = mapped_column(DateTime, default=func.current_date())
    status: Mapped[str] = mapped_column(String(20)) # 'success', 'partial', 'fail'
    
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())