FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Копирование requirements и установка зависимостей
COPY requirements.txt .
RUN pip install -r requirements.txt

# Копирование кода
COPY telegram-bot/ ./telegram-bot/
COPY config/ ./config/
COPY core/ ./core/
COPY services/ ./services/
COPY database/ ./database/
COPY helpers/ ./helpers/
COPY domain/ ./domain/
COPY infrastructure/ ./infrastructure/

# Создание директорий для логов и данных
RUN mkdir -p /app/logs /app/data

# Порт (не используется для бота, но на будущее)
EXPOSE 8080

# Запуск бота
CMD ["python", "telegram-bot/bot.py"]
