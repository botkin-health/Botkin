# 🔄 Инструкция по восстановлению бэкапа HealthVault

> **Как вернуться к состоянию проекта на момент создания бэкапа**

---

## 📍 Где найти бэкап?

Бэкапы хранятся в директории `backups/` на уровень выше проекта:

```
~/HealthVault/              # Текущий проект
../backups/                 # Директория с бэкапами
  └── HealthVault_backup_2026-01-08_20-30-45.tar.gz
```

**Полный путь к бэкапам:**
```bash
# Если проект в ~/HealthVault
~/backups/HealthVault_backup_*.tar.gz

# Или найти все бэкапы:
find ~ -name "HealthVault_backup_*.tar.gz" 2>/dev/null
```

---

## 🔍 Как найти нужный бэкап?

### Вариант 1: По дате в имени файла

Имя бэкапа содержит дату и время: `HealthVault_backup_2026-01-08_20-30-45.tar.gz`

```bash
# Найти все бэкапы
ls -lh ~/backups/HealthVault_backup_*.tar.gz

# Найти бэкап за конкретную дату
ls -lh ~/backups/HealthVault_backup_2026-01-08*.tar.gz
```

### Вариант 2: По содержимому BACKUP_INFO.md

```bash
# Распаковать временно и посмотреть информацию
cd /tmp
tar -xzf ~/backups/HealthVault_backup_2026-01-08_20-30-45.tar.gz
cat HealthVault_backup_*/BACKUP_INFO.md
```

---

## 🚀 Как восстановить бэкап?

### ⚠️ ВАЖНО: Перед восстановлением

1. **Сохрани текущее состояние** (если нужно):
   ```bash
   cd ~/HealthVault
   git status  # Посмотреть, что изменилось
   git commit -am "Сохраняю состояние перед восстановлением бэкапа"
   ```

2. **Создай бэкап текущего состояния** (на всякий случай):
   ```bash
   cd ~/HealthVault
   ./scripts/create_backup.sh
   ```

### Шаг 1: Найти нужный бэкап

```bash
# Перейти в директорию с бэкапами
cd ~/backups

# Посмотреть список бэкапов
ls -lh HealthVault_backup_*.tar.gz

# Выбрать нужный (например, последний)
BACKUP_FILE="HealthVault_backup_2026-01-08_20-30-45.tar.gz"
```

### Шаг 2: Распаковать бэкап во временную директорию

```bash
# Создать временную директорию
TEMP_DIR=$(mktemp -d)
cd "${TEMP_DIR}"

# Распаковать бэкап
tar -xzf ~/backups/${BACKUP_FILE}

# Посмотреть содержимое
ls -la
```

### Шаг 3: Восстановить файлы

**Вариант A: Полное восстановление (заменить весь проект)**

```bash
# ⚠️ ВНИМАНИЕ: Это заменит весь проект!
# Убедись, что сохранил текущее состояние

# Перейти в корень проекта
cd ~/HealthVault

# Создать бэкап текущего состояния (на всякий случай)
./scripts/create_backup.sh

# Удалить текущий проект (или переименовать)
mv ~/HealthVault ~/HealthVault_old_$(date +%Y%m%d)

# Скопировать восстановленные файлы
cp -r "${TEMP_DIR}/HealthVault_backup_*"/* ~/HealthVault/
```

**Вариант B: Выборочное восстановление (только нужные файлы)**

```bash
# Восстановить только исходный код
cd ~/HealthVault
cp -r "${TEMP_DIR}/HealthVault_backup_*/telegram-bot"/* telegram-bot/
cp -r "${TEMP_DIR}/HealthVault_backup_*/scripts"/* scripts/

# Восстановить базы знаний
cp "${TEMP_DIR}/HealthVault_backup_*/knowledge_base.json" .
cp "${TEMP_DIR}/HealthVault_backup_*/data/nutrition/nutrition_log.json" data/nutrition/
cp "${TEMP_DIR}/HealthVault_backup_*/data/workouts_database.json" data/

# Восстановить документацию
cp "${TEMP_DIR}/HealthVault_backup_*"/*.md .

# Восстановить конфигурацию
cp "${TEMP_DIR}/HealthVault_backup_*/.gitignore" .
cp "${TEMP_DIR}/HealthVault_backup_*/requirements.txt" .
```

### Шаг 4: Восстановить окружение

```bash
cd ~/HealthVault

# Создать виртуальное окружение (если его нет)
python3 -m venv venv
source venv/bin/activate

# Установить зависимости
pip install -r requirements.txt
cd telegram-bot
pip install -r requirements.txt
cd ..
```

### Шаг 5: Восстановить API ключи (если нужно)

**⚠️ Ключи НЕ включены в бэкап для безопасности!**

Если нужно восстановить ключи:

```bash
# Telegram Bot Token
# Спросить у владельца или создать новый через @BotFather
echo "TELEGRAM_BOT_TOKEN=ваш_токен" > telegram-bot/.env

# OpenAI API Key (если нужен)
echo "ваш_ключ" > .openai_api_key
chmod 600 .openai_api_key

# Google Vision API Key (если нужен)
echo "ваш_ключ" > .google_vision_api_key
chmod 600 .google_vision_api_key
```

### Шаг 6: Проверить восстановление

```bash
cd ~/HealthVault

# Проверить структуру
ls -la
ls -la telegram-bot/
ls -la data/nutrition/

# Проверить, что файлы на месте
test -f knowledge_base.json && echo "✅ knowledge_base.json найден"
test -f data/nutrition/nutrition_log.json && echo "✅ nutrition_log.json найден"
test -f telegram-bot/bot.py && echo "✅ bot.py найден"

# Проверить Git статус
git status
```

### Шаг 7: Очистить временные файлы

```bash
# Удалить временную директорию
rm -rf "${TEMP_DIR}"
```

---

## 🆘 Если что-то пошло не так

### Проблема: "Файл не найден"

```bash
# Проверить, что бэкап распакован правильно
cd /tmp
tar -xzf ~/backups/HealthVault_backup_2026-01-08_20-30-45.tar.gz
ls -la HealthVault_backup_*/
```

### Проблема: "Конфликты с текущими файлами"

```bash
# Создать бэкап текущего состояния
cd ~/HealthVault
./scripts/create_backup.sh

# Восстановить только нужные файлы вручную
# (см. Вариант B выше)
```

### Проблема: "Бэкап не найден"

```bash
# Найти все бэкапы в системе
find ~ -name "HealthVault_backup_*.tar.gz" 2>/dev/null

# Проверить директорию backups
ls -la ~/backups/
```

---

## 📝 Пример полного восстановления

```bash
#!/bin/bash
# Полный скрипт восстановления

# 1. Найти последний бэкап
BACKUP_FILE=$(ls -t ~/backups/HealthVault_backup_*.tar.gz | head -1)
echo "Восстанавливаю из: ${BACKUP_FILE}"

# 2. Создать бэкап текущего состояния
cd ~/HealthVault
./scripts/create_backup.sh

# 3. Распаковать бэкап
TEMP_DIR=$(mktemp -d)
cd "${TEMP_DIR}"
tar -xzf "${BACKUP_FILE}"

# 4. Восстановить файлы
BACKUP_DIR=$(ls -d HealthVault_backup_* | head -1)
cd ~/HealthVault

# Исходный код
cp -r "${TEMP_DIR}/${BACKUP_DIR}/telegram-bot"/* telegram-bot/ 2>/dev/null
cp -r "${TEMP_DIR}/${BACKUP_DIR}/scripts"/* scripts/ 2>/dev/null

# Базы знаний
cp "${TEMP_DIR}/${BACKUP_DIR}/knowledge_base.json" . 2>/dev/null
cp "${TEMP_DIR}/${BACKUP_DIR}/data/nutrition/nutrition_log.json" data/nutrition/ 2>/dev/null
cp "${TEMP_DIR}/${BACKUP_DIR}/data/workouts_database.json" data/ 2>/dev/null

# Документация
cp "${TEMP_DIR}/${BACKUP_DIR}"/*.md . 2>/dev/null

# 5. Очистить
rm -rf "${TEMP_DIR}"

echo "✅ Восстановление завершено!"
```

---

## 💡 Советы

1. **Всегда создавай бэкап перед восстановлением** — на всякий случай
2. **Проверяй содержимое бэкапа** перед восстановлением (распаковать и посмотреть)
3. **Восстанавливай выборочно** — не обязательно заменять весь проект
4. **API ключи нужно восстановить отдельно** — они не в бэкапе

---

*Документ создан: 2026-01-08*
