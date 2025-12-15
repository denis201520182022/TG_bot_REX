# Используем стабильную версию (bookworm), она надежнее
FROM python:3.11-slim-bookworm

WORKDIR /app

# --- МАГИЯ УСКОРЕНИЯ ---
# Меняем зеркала Debian на Яндекс (для скорости)
RUN sed -i 's/deb.debian.org/mirror.yandex.ru/g' /etc/apt/sources.list.d/debian.sources

# Устанавливаем системные зависимости
# (теперь это займет 30-60 секунд вместо 30 минут)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем и ставим зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

ENV PYTHONPATH=/app