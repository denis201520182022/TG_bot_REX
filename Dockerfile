# Используем легкий образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Устанавливаем системные зависимости (нужны для сборки некоторых python библиотек)
# netcat нужен для проверки доступности портов (опционально), 
# libpq-dev нужен для psycopg2/asyncpg
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код проекта внутрь контейнера
COPY . .

# Устанавливаем переменную окружения, чтобы Python видел папку src
ENV PYTHONPATH=/app