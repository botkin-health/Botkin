#!/bin/bash
# Скрипт для создания бэкапа HealthVault перед передачей проекта
# Создает архив с исходниками, базами знаний и документацией

set -e  # Остановиться при ошибке

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Получаем дату для имени архива
BACKUP_DATE=$(date +%Y-%m-%d_%H-%M-%S)
BACKUP_NAME="HealthVault_backup_${BACKUP_DATE}"
BACKUP_DIR="../backups"
ARCHIVE_NAME="${BACKUP_NAME}.tar.gz"

echo -e "${GREEN}📦 Создание бэкапа HealthVault...${NC}"
echo "Дата: $(date)"
echo ""

# Создаем временную директорию для бэкапа
TEMP_DIR=$(mktemp -d)
BACKUP_ROOT="${TEMP_DIR}/${BACKUP_NAME}"

echo -e "${YELLOW}Создаю структуру бэкапа...${NC}"
mkdir -p "${BACKUP_ROOT}"

# Переходим в корень проекта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

echo -e "${YELLOW}Копирую исходный код...${NC}"

# 1. Исходный код telegram-bot (исключая venv, __pycache__, logs, media)
echo "  → telegram-bot/"
mkdir -p "${BACKUP_ROOT}/telegram-bot"
rsync -av --exclude='venv' \
          --exclude='__pycache__' \
          --exclude='*.pyc' \
          --exclude='logs' \
          --exclude='media' \
          --exclude='.env' \
          telegram-bot/ "${BACKUP_ROOT}/telegram-bot/"

# 2. Скрипты (исключая __pycache__)
echo "  → scripts/"
mkdir -p "${BACKUP_ROOT}/scripts"
rsync -av --exclude='__pycache__' \
          --exclude='*.pyc' \
          scripts/ "${BACKUP_ROOT}/scripts/"

echo -e "${YELLOW}Копирую базы знаний и данные...${NC}"

# 3. Базы знаний
echo "  → knowledge_base.json"
cp knowledge_base.json "${BACKUP_ROOT}/" 2>/dev/null || echo "    ⚠️  knowledge_base.json не найден"

# 4. Данные питания
echo "  → data/nutrition/"
mkdir -p "${BACKUP_ROOT}/data/nutrition"
if [ -f "data/nutrition/nutrition_log.json" ]; then
    cp data/nutrition/nutrition_log.json "${BACKUP_ROOT}/data/nutrition/"
fi

# 5. База тренировок
echo "  → data/workouts_database.*"
mkdir -p "${BACKUP_ROOT}/data"
if [ -f "data/workouts_database.json" ]; then
    cp data/workouts_database.json "${BACKUP_ROOT}/data/"
fi
if [ -f "data/workouts_database.md" ]; then
    cp data/workouts_database.md "${BACKUP_ROOT}/data/"
fi

# 6. Аналитические отчеты
echo "  → data/analysis/"
if [ -d "data/analysis" ]; then
    mkdir -p "${BACKUP_ROOT}/data/analysis"
    find data/analysis -type f \( -name "*.md" -o -name "*.json" -o -name "*.py" \) | while read file; do
        rel_path="${file#data/analysis/}"
        mkdir -p "${BACKUP_ROOT}/data/analysis/$(dirname "${rel_path}")"
        cp "${file}" "${BACKUP_ROOT}/data/analysis/${rel_path}"
    done
fi

# 7. Логи данных (JSON)
echo "  → data/logs/"
if [ -d "data/logs" ]; then
    mkdir -p "${BACKUP_ROOT}/data/logs"
    find data/logs -type f -name "*.json" | while read file; do
        rel_path="${file#data/logs/}"
        mkdir -p "${BACKUP_ROOT}/data/logs/$(dirname "${rel_path}")"
        cp "${file}" "${BACKUP_ROOT}/data/logs/${rel_path}"
    done
fi

# 8. Замеры веса
echo "  → data/weights/"
if [ -d "data/weights" ]; then
    mkdir -p "${BACKUP_ROOT}/data/weights"
    find data/weights -type f -name "*.json" | while read file; do
        rel_path="${file#data/weights/}"
        mkdir -p "${BACKUP_ROOT}/data/weights/$(dirname "${rel_path}")"
        cp "${file}" "${BACKUP_ROOT}/data/weights/${rel_path}"
    done
fi

# 9. Кровяное давление
echo "  → data/blood-pressure/"
if [ -d "data/blood-pressure" ]; then
    mkdir -p "${BACKUP_ROOT}/data/blood-pressure"
    find data/blood-pressure -type f -name "*.json" | while read file; do
        rel_path="${file#data/blood-pressure/}"
        mkdir -p "${BACKUP_ROOT}/data/blood-pressure/$(dirname "${rel_path}")"
        cp "${file}" "${BACKUP_ROOT}/data/blood-pressure/${rel_path}"
    done
fi

# 10. Тестовые напоминания
if [ -f "data/test_reminders.json" ]; then
    echo "  → data/test_reminders.json"
    mkdir -p "${BACKUP_ROOT}/data"
    cp data/test_reminders.json "${BACKUP_ROOT}/data/"
fi

echo -e "${YELLOW}Копирую документацию...${NC}"

# 11. Документация в корне
echo "  → *.md файлы"
for md_file in *.md; do
    if [ -f "${md_file}" ]; then
        cp "${md_file}" "${BACKUP_ROOT}/"
    fi
done

# 12. Конфигурационные файлы
echo "  → Конфигурация"
cp .gitignore "${BACKUP_ROOT}/" 2>/dev/null || echo "    ⚠️  .gitignore не найден"
cp requirements.txt "${BACKUP_ROOT}/" 2>/dev/null || echo "    ⚠️  requirements.txt не найден"

# 13. .env.example если есть
if [ -f "telegram-bot/.env.example" ]; then
    cp telegram-bot/.env.example "${BACKUP_ROOT}/telegram-bot/"
fi

# Создаем файл с информацией о бэкапе
echo -e "${YELLOW}Создаю README бэкапа...${NC}"
cat > "${BACKUP_ROOT}/BACKUP_INFO.md" << EOF
# Информация о бэкапе

**Дата создания:** $(date)
**Версия проекта:** HealthVault (состояние на момент бэкапа)
**Причина:** Бэкап перед передачей проекта другой системе (Антигравити)

## Что включено в бэкап:

✅ **Исходный код:**
- telegram-bot/ (код бота, обработчики, сервисы)
- scripts/ (скрипты обработки данных)

✅ **Базы знаний:**
- knowledge_base.json
- data/nutrition/nutrition_log.json
- data/workouts_database.json
- data/workouts_database.md
- data/analysis/ (аналитические отчеты)
- data/logs/ (JSON логи)
- data/weights/ (замеры веса)
- data/blood-pressure/ (данные давления)

✅ **Документация:**
- Все .md файлы в корне проекта
- telegram-bot/README.md

✅ **Конфигурация:**
- .gitignore
- requirements.txt
- telegram-bot/requirements.txt
- telegram-bot/.env.example

## Что НЕ включено (намеренно):

❌ **Большие файлы данных:**
- data/blood-tests/*.pdf (PDF анализов)
- data/covid-tests/*.pdf
- data/garmin/*.json (слишком много файлов)
- data/apple-health/export/*.xml
- data/media/ (фото)
- data/genetics/*.pdf, *.jpg
- data/hormones/*.pdf
- data/ultrasound/*.docx
- data/urine-tests/*.pdf
- data/vitamins/*.pdf
- data/medical-records/*.pdf, *.docx

❌ **Временные файлы:**
- venv/ (виртуальное окружение)
- __pycache__/ (кэш Python)
- *.log (логи)
- telegram-bot/logs/
- telegram-bot/media/

❌ **Секреты:**
- .env (Telegram Bot Token)
- .openai_api_key
- .google_vision_api_key

## Как восстановить бэкап:

См. файл RESTORE_BACKUP.md в корне проекта или инструкцию ниже.

EOF

# Создаем архив
echo -e "${YELLOW}Создаю архив...${NC}"
mkdir -p "${BACKUP_DIR}"
cd "${TEMP_DIR}"
tar -czf "${PROJECT_ROOT}/${BACKUP_DIR}/${ARCHIVE_NAME}" "${BACKUP_NAME}"

# Удаляем временную директорию
rm -rf "${TEMP_DIR}"

# Вычисляем размер архива
ARCHIVE_SIZE=$(du -h "${PROJECT_ROOT}/${BACKUP_DIR}/${ARCHIVE_NAME}" | cut -f1)

echo ""
echo -e "${GREEN}✅ Бэкап создан успешно!${NC}"
echo ""
echo "📦 Архив: ${BACKUP_DIR}/${ARCHIVE_NAME}"
echo "📊 Размер: ${ARCHIVE_SIZE}"
echo ""
echo "📍 Расположение:"
echo "   $(cd "${PROJECT_ROOT}" && pwd)/${BACKUP_DIR}/${ARCHIVE_NAME}"
echo ""
echo -e "${YELLOW}💡 Для восстановления см. RESTORE_BACKUP.md${NC}"
