# HealthVault — Руководство для разработчиков

> **Документ для передачи проекта другому разработчику/AI (например, Антигравити)**

## ⚡ Быстрая навигация для Антигравити

**Если ты только начинаешь работу с проектом:**

1. **Прочитай этот документ полностью** — здесь все необходимое
2. **Проверь наличие ключей** (см. раздел "🔑 API ключи и секреты" ниже)
3. **Если ключей нет — спроси разрешение у владельца** перед созданием новых
4. **Следуй инструкциям в разделе "🚀 Быстрый старт"** для запуска

**Где найти ключи:**
- Telegram Bot Token: `telegram-bot/.env` (файл `TELEGRAM_BOT_TOKEN=...`)
- OpenAI API Key: `.openai_api_key` в корне проекта
- Google Vision API Key: `.google_vision_api_key` в корне проекта

**Если ключей нет — см. подробные инструкции ниже с конкретными ссылками на сервисы.**

---

## 📋 Что это за проект?

**HealthVault** — персональная система для отслеживания здоровья, питания, тренировок и медицинских анализов. Основной интерфейс — Telegram-бот, который помогает:
- Логировать питание (текст/фото) с автоматическим расчетом КБЖУ
- Отслеживать медицинские анализы
- Анализировать данные из Garmin, Apple Health, SleepCycle
- Давать рекомендации на основе анализов и целей

---

## 🎯 Основные цели проекта

1. **Автоматизация учета питания** — распознавание еды из фото/текста, расчет КБЖУ
2. **Анализ медицинских данных** — структурирование анализов, отслеживание динамики
3. **Интеграция данных** — объединение данных из разных источников (Garmin, Apple Health, анализы)
4. **Персонализированные рекомендации** — советы по питанию, добавкам, тренировкам на основе данных

---

## 📁 Структура проекта

```
HealthVault/
├── README.md                    # Главная документация
├── ARCHITECTURE.md              # Архитектура (база знаний vs контекст)
├── HEALTH.md                    # Профиль здоровья пользователя
├── KNOWLEDGE_BASE.md            # База знаний по анализам
├── ONBOARDING.md                # Этот документ
│
├── telegram-bot/                # Telegram-бот (основной интерфейс)
│   ├── bot.py                   # Точка входа
│   ├── handlers/                # Обработчики сообщений
│   │   ├── commands.py          # Команды (/start, /status, /help)
│   │   ├── photo.py             # Обработка фото
│   │   └── text.py              # Обработка текста
│   ├── services/                # Бизнес-логика
│   │   ├── nutrition.py         # Расчет КБЖУ
│   │   ├── description_parser.py # Парсинг описаний еды
│   │   ├── menu_parser.py       # Распознавание меню/упаковок
│   │   ├── chatgpt_vision.py    # ChatGPT Vision API
│   │   ├── api_key_loader.py    # Загрузка API ключей
│   │   └── ...
│   ├── data/
│   │   └── products.json        # База продуктов с КБЖУ
│   └── requirements.txt         # Зависимости бота
│
├── scripts/                      # Скрипты обработки данных
│   ├── garmin/                  # Загрузка данных Garmin
│   ├── apple-health/            # Парсинг Apple Health
│   ├── sleepcycle/              # Обработка SleepCycle
│   └── google_vision_ocr.py     # OCR для распознавания документов
│
└── data/                        # Данные проекта
    ├── nutrition/
    │   └── nutrition_log.json   # Лог питания (JSON)
    ├── blood-tests/             # PDF анализов крови
    ├── garmin/                  # Данные Garmin (JSON)
    ├── apple-health/            # Данные Apple Health (XML/JSON)
    └── ...
```

---

## 🔑 API ключи и секреты

### ⚠️ ВАЖНО: Ключи НЕ хранятся в репозитории

Все ключи исключены из Git через `.gitignore`:
- `.env`
- `.google_vision_api_key`
- `.openai_api_key`
- `*.key`, `*.pem`

### 📍 Где хранятся ключи (приоритет загрузки):

#### 1. **Telegram Bot Token** (ОБЯЗАТЕЛЬНО)

**Где искать существующий ключ:**
- Файл `telegram-bot/.env` (проверить наличие `TELEGRAM_BOT_TOKEN=...`)
- Переменная окружения `TELEGRAM_BOT_TOKEN`

**Как получить новый ключ (пошагово):**

1. **Открыть Telegram и найти бота [@BotFather](https://t.me/BotFather)**
   - Ссылка: https://t.me/BotFather
   - Или найти в поиске Telegram: `@BotFather`

2. **Создать нового бота или получить токен существующего:**
   ```
   /newbot          # Создать нового бота
   /token           # Получить токен существующего бота
   ```
   
3. **Следовать инструкциям BotFather:**
   - При создании нового бота: ввести имя и username
   - BotFather выдаст токен вида: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`

4. **Сохранить токен в файл:**
   ```bash
   cd telegram-bot
   # Создать или отредактировать .env файл
   echo "TELEGRAM_BOT_TOKEN=ваш_токен_от_BotFather" > .env
   ```
   
   **Формат файла `.env`:**
   ```
   TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   ```

**⚠️ Если у владельца проекта уже есть бот:**
- Спросить у владельца токен существующего бота
- Или попросить владельца выполнить `/token` в чате с @BotFather

---

#### 2. **OpenAI API Key (ChatGPT Vision)** (ОПЦИОНАЛЬНО, но рекомендуется)

**Где искать существующий ключ:**
- Файл `.openai_api_key` в корне HealthVault (проверить: `cat .openai_api_key`)
- Файл `~/FamilyDocs/.openai_api_key` (если есть)
- Переменная окружения `OPENAI_API_KEY`

**Как получить новый ключ (пошагово):**

1. **Зарегистрироваться/войти на [platform.openai.com](https://platform.openai.com)**
   - Ссылка: https://platform.openai.com
   - Если нет аккаунта: нажать "Sign up" и создать аккаунт
   - Если есть аккаунт: войти

2. **Перейти в раздел API Keys:**
   - В меню слева выбрать: **"API keys"** или **"API Keys"**
   - Или прямая ссылка: https://platform.openai.com/api-keys

3. **Создать новый API ключ:**
   - Нажать кнопку **"Create new secret key"**
   - Ввести название (например, "HealthVault Bot")
   - Нажать **"Create secret key"**
   - ⚠️ **ВАЖНО:** Скопировать ключ сразу! Он показывается только один раз
   - Ключ выглядит как: `sk-proj-...` (начинается с `sk-`)

4. **Сохранить ключ в файл:**
   ```bash
   # В корне HealthVault
   echo "sk-proj-ваш_ключ_здесь" > .openai_api_key
   chmod 600 .openai_api_key  # Установить права только для чтения владельцем
   ```

5. **Проверить баланс (опционально):**
   - Перейти в раздел "Billing" или "Usage"
   - Убедиться, что есть кредиты на счету (ChatGPT Vision API платный)

**⚠️ Если у владельца проекта уже есть ключ:**
- Спросить у владельца ключ
- Или попросить владельца создать новый ключ и предоставить его

---

#### 3. **Google Vision API Key (OCR)** (ОПЦИОНАЛЬНО, запасной вариант)

**Где искать существующий ключ:**
- Файл `.google_vision_api_key` в корне HealthVault (проверить: `cat .google_vision_api_key`)
- Файл `~/FamilyDocs/.google_vision_api_key` (если есть)
- Переменная окружения `GOOGLE_VISION_API_KEY`

**Как получить новый ключ (пошагово):**

1. **Создать проект в Google Cloud Console:**
   - Перейти на [console.cloud.google.com](https://console.cloud.google.com)
   - Ссылка: https://console.cloud.google.com
   - Войти с Google аккаунтом

2. **Создать новый проект (если нужно):**
   - Нажать на выпадающий список проектов вверху
   - Выбрать **"New Project"**
   - Ввести название (например, "HealthVault OCR")
   - Нажать **"Create"**

3. **Включить Google Vision API:**
   - В меню слева: **"APIs & Services"** → **"Library"**
   - Или прямая ссылка: https://console.cloud.google.com/apis/library
   - В поиске ввести: **"Cloud Vision API"**
   - Выбрать **"Cloud Vision API"**
   - Нажать **"Enable"**

4. **Создать API ключ:**
   - Перейти в **"APIs & Services"** → **"Credentials"**
   - Или прямая ссылка: https://console.cloud.google.com/apis/credentials
   - Нажать **"Create Credentials"** → **"API Key"**
   - Скопировать созданный ключ (выглядит как: `AIza...`)

5. **Ограничить ключ (рекомендуется для безопасности):**
   - Нажать на созданный ключ для редактирования
   - В разделе **"API restrictions"** выбрать **"Restrict key"**
   - Выбрать **"Cloud Vision API"**
   - Нажать **"Save"**

6. **Сохранить ключ в файл:**
   ```bash
   # В корне HealthVault
   echo "AIzaваш_ключ_здесь" > .google_vision_api_key
   chmod 600 .google_vision_api_key  # Установить права только для чтения владельцем
   ```

7. **Настроить биллинг (если нужно):**
   - Google Cloud предоставляет бесплатный tier (первые 1000 запросов/месяц бесплатно)
   - Если нужно больше: настроить биллинг в разделе "Billing"

**⚠️ Если у владельца проекта уже есть ключ:**
- Спросить у владельца ключ
- Или попросить владельца создать новый ключ и предоставить его

---

### 📝 Инструкция для Антигравити (автоматический поиск ключей):

**Шаг 1: Проверить существующие ключи**

```bash
# Перейти в корень проекта
cd /path/to/HealthVault

# Проверить Telegram Bot Token
if [ -f "telegram-bot/.env" ]; then
    echo "✅ Найден .env файл:"
    grep TELEGRAM_BOT_TOKEN telegram-bot/.env
else
    echo "❌ .env файл не найден"
fi

# Проверить OpenAI API Key
if [ -f ".openai_api_key" ]; then
    echo "✅ Найден .openai_api_key файл"
    # Не показывать ключ полностью, только первые символы
    head -c 10 .openai_api_key && echo "..."
else
    echo "❌ .openai_api_key файл не найден"
fi

# Проверить Google Vision API Key
if [ -f ".google_vision_api_key" ]; then
    echo "✅ Найден .google_vision_api_key файл"
    head -c 10 .google_vision_api_key && echo "..."
else
    echo "❌ .google_vision_api_key файл не найден"
fi

# Проверить альтернативное расположение
if [ -f "$HOME/FamilyDocs/.openai_api_key" ]; then
    echo "✅ Найден .openai_api_key в ~/FamilyDocs/"
fi
```

**Шаг 2: Если ключи не найдены — спросить у владельца**

Если ключи не найдены, **спросить у владельца проекта (Александра):**

> "Привет! Я настраиваю HealthVault и не нашел API ключи в проекте. Мне нужны:
> 1. Telegram Bot Token (для запуска бота)
> 2. OpenAI API Key (для ChatGPT Vision, опционально)
> 3. Google Vision API Key (для OCR, опционально)
> 
> Можешь предоставить их? Или я могу создать новые ключи для тестирования?"

**Шаг 3: Если владелец предоставил ключи — сохранить их**

```bash
# Telegram Bot Token
cd telegram-bot
echo "TELEGRAM_BOT_TOKEN=токен_от_владельца" > .env
cd ..

# OpenAI API Key
echo "ключ_от_владельца" > .openai_api_key
chmod 600 .openai_api_key

# Google Vision API Key
echo "ключ_от_владельца" > .google_vision_api_key
chmod 600 .google_vision_api_key
```

**Шаг 4: Если владелец разрешил создать новые ключи — следовать инструкциям выше**

Создать ключи по инструкциям выше и **спросить разрешение** перед использованием:
- "Создал новый Telegram бот для тестирования. Можно использовать его токен?"
- "Создал OpenAI API ключ. Можно использовать его? (будет расходоваться баланс)"
- "Создал Google Vision API ключ. Можно использовать его?"

---

### ✅ Проверка наличия всех ключей

После настройки проверить:

```bash
# Проверить Telegram Bot Token
python3 -c "
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv('telegram-bot/.env')
token = os.getenv('TELEGRAM_BOT_TOKEN')
if token:
    print('✅ Telegram Bot Token найден')
else:
    print('❌ Telegram Bot Token не найден')
"

# Проверить OpenAI API Key
if [ -f ".openai_api_key" ]; then
    key=$(cat .openai_api_key | tr -d '\n')
    if [ ${#key} -gt 20 ]; then
        echo "✅ OpenAI API Key найден (длина: ${#key} символов)"
    else
        echo "❌ OpenAI API Key слишком короткий или пустой"
    fi
else
    echo "⚠️  OpenAI API Key не найден (опционально)"
fi

# Проверить Google Vision API Key
if [ -f ".google_vision_api_key" ]; then
    key=$(cat .google_vision_api_key | tr -d '\n')
    if [ ${#key} -gt 20 ]; then
        echo "✅ Google Vision API Key найден (длина: ${#key} символов)"
    else
        echo "❌ Google Vision API Key слишком короткий или пустой"
    fi
else
    echo "⚠️  Google Vision API Key не найден (опционально)"
fi
```

---

## 🚀 Быстрый старт

### 1. Клонирование и настройка

```bash
# Клонировать репозиторий
git clone <repository_url>
cd HealthVault

# Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate  # На macOS/Linux
# или
venv\Scripts\activate  # На Windows

# Установить зависимости
pip install -r requirements.txt
cd telegram-bot
pip install -r requirements.txt
```

### 2. Настройка ключей

```bash
# Создать .env файл для бота
cd telegram-bot
cp .env.example .env  # Если есть пример
# Или создать вручную:
echo "TELEGRAM_BOT_TOKEN=ваш_токен" > .env

# Создать файлы для API ключей (опционально)
cd ..
echo "ваш_openai_key" > .openai_api_key
echo "ваш_google_vision_key" > .google_vision_api_key
```

### 3. Запуск бота

```bash
cd telegram-bot
./start.sh
# Или вручную:
source ../venv/bin/activate
python3 bot.py
```

---

## 🐛 Где искать ошибки?

### 1. **Логи бота**
- `telegram-bot/logs/bot.log` — основные логи
- Консольный вывод при запуске

### 2. **Типичные проблемы:**

#### Бот не запускается:
- ❌ `TELEGRAM_BOT_TOKEN не найден` → Создать `.env` файл с токеном
- ❌ `ModuleNotFoundError` → Установить зависимости: `pip install -r requirements.txt`
- ❌ `ImportError` → Проверить, что виртуальное окружение активировано

#### Фото не обрабатываются:
- ❌ `OpenAI API ключ не найден` → Создать `.openai_api_key` или установить `OPENAI_API_KEY`
- ❌ `Google Vision API ключ не найден` → Создать `.google_vision_api_key` или установить `GOOGLE_VISION_API_KEY`
- ❌ `OCR не распознал текст` → Проверить качество фото, формат (JPG/PNG)

#### Неправильный расчет КБЖУ:
- Проверить логи в `telegram-bot/logs/bot.log`
- Проверить, что продукты есть в `telegram-bot/data/products.json`
- Проверить, что ChatGPT/OCR правильно распознал значения на упаковке

### 3. **Отладка:**

```bash
# Включить детальное логирование
export PYTHONPATH=/path/to/HealthVault/telegram-bot:$PYTHONPATH
python3 -u telegram-bot/bot.py 2>&1 | tee debug.log

# Проверить импорты
python3 -c "from telegram-bot.services.nutrition import *; print('OK')"
```

---

## 📚 Ключевые документы

1. **`README.md`** — общее описание проекта
2. **`ARCHITECTURE.md`** — архитектура (база знаний vs контекст чата)
3. **`HEALTH.md`** — профиль здоровья пользователя, цели, добавки
4. **`KNOWLEDGE_BASE.md`** — база знаний по медицинским анализам
5. **`HOW_TO_WORK_WITH_CONTEXT.md`** — как работать с контекстом в разных чатах
6. **`telegram-bot/README.md`** — документация по боту

---

## 🔍 Что проверить при переносе проекта?

### 1. **Зависимости:**
```bash
# Проверить, что все установлено
pip list | grep -E "aiogram|openai|google|pillow|pypdfium"
```

### 2. **Структура файлов:**
```bash
# Проверить наличие ключевых файлов
ls -la telegram-bot/data/products.json
ls -la data/nutrition/nutrition_log.json
ls -la .gitignore
```

### 3. **Права доступа:**
```bash
# Убедиться, что скрипты исполняемые
chmod +x telegram-bot/start.sh
```

### 4. **Конфигурация:**
- Проверить наличие `.env` файла
- Проверить наличие API ключей (если нужны)
- Проверить, что пути к данным корректны

---

## 🎯 Планы развития

### Текущие задачи (2026-01-08):
1. ✅ Улучшение распознавания еды (cooked vs dry)
2. ✅ Недельный учет питания с категориями
3. ✅ Модуль артериального давления
4. 🔄 Исправление ошибок распознавания КБЖУ из упаковок
5. 🔄 Удаление дубликатов продуктов

### Будущие планы:
- Интеграция с Apple Health для автоматической синхронизации
- Анализ трендов по питанию и здоровью
- Рекомендации на основе машинного обучения
- Экспорт данных в различные форматы

---

## 💡 Советы для работы с проектом

### 1. **Всегда читай из файлов:**
```python
# ✅ Правильно
import json
with open('data/nutrition/nutrition_log.json') as f:
    data = json.load(f)

# ❌ Неправильно
# "Помни, что я ел вчера..." (в контексте чата)
```

### 2. **Используй Git для версионирования:**
```bash
# Коммитить изменения в базу знаний
git add data/nutrition/nutrition_log.json
git commit -m "Обновлен лог питания"
```

### 3. **Тестируй изменения:**
```bash
# Запустить бота в тестовом режиме
python3 telegram-bot/bot.py
# Отправить тестовое сообщение в бот
```

---

## 📞 Контакты и поддержка

- **Владелец проекта:** Александр
- **Репозиторий:** (указать URL, если есть)
- **Документация:** См. файлы в корне проекта

---

## ⚠️ Важные замечания

1. **Секреты не в Git:** Все API ключи и токены исключены из репозитория
2. **База знаний на диске:** Источник истины — файлы JSON, не контекст чата
3. **Версионирование:** Все изменения в базу знаний должны коммититься в Git
4. **Тестирование:** Перед изменением логики тестировать на реальных данных

---

*Документ создан: 2026-01-08*  
*Для передачи проекта другому разработчику/AI*
