# Быстрый старт для Антигравити

> **Краткая инструкция для начала работы с проектом**

---

## ✅ Что уже есть в проекте?

1. **Документация:**
   - ✅ `README.md` — общее описание
   - ✅ `ARCHITECTURE.md` — архитектура проекта
   - ✅ `ONBOARDING.md` — подробное руководство для разработчиков
   - ✅ `HEALTH.md` — профиль здоровья пользователя
   - ✅ `KNOWLEDGE_BASE.md` — база знаний по анализам

2. **Код:**
   - ✅ Telegram-бот с обработкой фото/текста
   - ✅ Модули распознавания еды (ChatGPT Vision + OCR)
   - ✅ Расчет КБЖУ
   - ✅ Скрипты обработки данных

3. **Структура:**
   - ✅ Организованная структура папок
   - ✅ `.gitignore` настроен правильно
   - ✅ `requirements.txt` для зависимостей

---

## ❌ Чего НЕТ в репозитории (и это нормально):

1. **API ключи и токены:**
   - ❌ Telegram Bot Token
   - ❌ OpenAI API Key
   - ❌ Google Vision API Key
   
   **Почему:** Они исключены из Git для безопасности (см. `.gitignore`)

2. **Виртуальное окружение:**
   - ❌ `venv/` папка
   
   **Почему:** Создается локально при установке

---

## 🚀 Что нужно сделать для запуска?

### Шаг 1: Получить ключи

**Антигравити должен сначала проверить, есть ли ключи в проекте, затем спросить разрешение у владельца.**

#### 🔍 Шаг 1.1: Проверить существующие ключи

```bash
# Перейти в корень проекта
cd HealthVault

# Проверить Telegram Bot Token
if [ -f "telegram-bot/.env" ]; then
    echo "✅ Найден .env файл с Telegram Bot Token"
    grep -q "TELEGRAM_BOT_TOKEN" telegram-bot/.env && echo "   Токен присутствует в файле"
else
    echo "❌ .env файл не найден"
fi

# Проверить OpenAI API Key
if [ -f ".openai_api_key" ]; then
    echo "✅ Найден .openai_api_key файл"
else
    echo "❌ .openai_api_key файл не найден"
fi

# Проверить Google Vision API Key
if [ -f ".google_vision_api_key" ]; then
    echo "✅ Найден .google_vision_api_key файл"
else
    echo "❌ .google_vision_api_key файл не найден"
fi
```

#### 💬 Шаг 1.2: Если ключи не найдены — спросить у владельца

**Спросить у владельца проекта (Александра):**

> "Привет! Я настраиваю HealthVault и не нашел API ключи в проекте. Мне нужны:
> 1. **Telegram Bot Token** (обязательно) — для запуска бота
> 2. **OpenAI API Key** (опционально) — для ChatGPT Vision
> 3. **Google Vision API Key** (опционально) — для OCR
> 
> Можешь предоставить их? Или я могу создать новые ключи для тестирования?"

#### 📝 Шаг 1.3: Как получить ключи (если владелец разрешил)

**Telegram Bot Token (ОБЯЗАТЕЛЬНО):**
1. Открыть [@BotFather](https://t.me/BotFather) в Telegram
2. Выполнить `/newbot` или `/token`
3. Получить токен вида: `1234567890:ABCdef...`
4. Сохранить в `telegram-bot/.env`:
   ```bash
   echo "TELEGRAM_BOT_TOKEN=ваш_токен" > telegram-bot/.env
   ```

**OpenAI API Key (опционально, но рекомендуется):**
1. Зайти на [platform.openai.com](https://platform.openai.com)
2. Перейти в "API keys": https://platform.openai.com/api-keys
3. Создать новый ключ (начинается с `sk-`)
4. Сохранить в `.openai_api_key`:
   ```bash
   echo "sk-ваш_ключ" > .openai_api_key
   chmod 600 .openai_api_key
   ```

**Google Vision API Key (опционально):**
1. Зайти на [console.cloud.google.com](https://console.cloud.google.com)
2. Создать проект и включить "Cloud Vision API"
3. Создать API ключ в разделе "Credentials"
4. Сохранить в `.google_vision_api_key`:
   ```bash
   echo "AIzaваш_ключ" > .google_vision_api_key
   chmod 600 .google_vision_api_key
   ```

**📖 Подробные инструкции:** См. раздел "🔑 API ключи и секреты" в `ONBOARDING.md`

### Шаг 2: Настроить окружение

```bash
# 1. Клонировать репозиторий (если еще не клонирован)
git clone <repository_url>
cd HealthVault

# 2. Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# или
venv\Scripts\activate  # Windows

# 3. Установить зависимости
pip install -r requirements.txt
cd telegram-bot
pip install -r requirements.txt

# 4. Создать .env файл
cp .env.example .env
# Отредактировать .env и добавить токен:
# TELEGRAM_BOT_TOKEN=ваш_токен

# 5. (Опционально) Создать файлы для API ключей
cd ..
echo "ваш_openai_key" > .openai_api_key
echo "ваш_google_vision_key" > .google_vision_api_key
```

### Шаг 3: Запустить бота

```bash
cd telegram-bot
./start.sh
# Или вручную:
source ../venv/bin/activate
python3 bot.py
```

---

## 🔍 Где искать ошибки?

### Типичные проблемы:

1. **Бот не запускается:**
   - Проверить наличие `.env` файла с `TELEGRAM_BOT_TOKEN`
   - Проверить, что зависимости установлены: `pip install -r requirements.txt`
   - Проверить логи: `telegram-bot/logs/bot.log`

2. **Фото не обрабатываются:**
   - Проверить наличие API ключей (OpenAI или Google Vision)
   - Проверить логи на ошибки распознавания
   - Проверить формат фото (JPG/PNG)

3. **Неправильный расчет КБЖУ:**
   - Проверить логи в `telegram-bot/logs/bot.log`
   - Проверить базу продуктов: `telegram-bot/data/products.json`
   - Проверить, что ChatGPT/OCR правильно распознал значения

---

## 📚 Что читать дальше?

1. **`ONBOARDING.md`** — подробное руководство со всеми деталями
2. **`ARCHITECTURE.md`** — как устроен проект внутри
3. **`telegram-bot/README.md`** — документация по боту

---

## 💡 Советы

1. **Всегда читай из файлов:**
   - База знаний: `knowledge_base.json`
   - Питание: `data/nutrition/nutrition_log.json`
   - Не полагайся на контекст чата как источник данных

2. **Используй Git:**
   - Все изменения в базу знаний коммитить
   - Ключи НЕ коммитить (они в `.gitignore`)

3. **Тестируй изменения:**
   - Запускать бота локально
   - Проверять логи
   - Тестировать на реальных данных

---

*Документ создан: 2026-01-08*
