# Руководство по развёртыванию

## Важно: Обновление кода в Docker

⚠️ **КРИТИЧНО**: Код бота **встроен в Docker образ** при сборке.

Это значит:
- ❌ `rsync` для обновления файлов + `docker restart` **НЕ применяет** изменения кода
- ✅ Вы **ОБЯЗАНЫ пересобрать** Docker образ чтобы обновить код

## Архитектура

```
Локальная машина
/Users/.../HealthVault/
        │
        │ rsync (загружает файлы)
        ▼
Сервер 146.103.111.109
/root/healthvault/  ◄─── Файлы на диске
        │
        │ docker-compose build (встраивает код в образ)
        ▼
Docker Image
healthvault-bot  ◄─── Код встроен при сборке
        │
        │ docker-compose up (создаёт контейнер)
        ▼
Запущенный контейнер
healthvault_bot  ◄─── Использует код ИЗ ОБРАЗА,
                      НЕ из /root/healthvault/!

⚠️ Поэтому rsync + restart НЕ обновляет код!
   Нужен docker-compose build!
```

## Неправильный способ ❌

```bash
# Загрузить файлы
rsync -avz core/ root@146.103.111.109:/root/healthvault/core/

# Перезапустить контейнер
docker restart healthvault_bot

# ❌ ПРОБЛЕМА: Контейнер всё ещё использует СТАРЫЙ код из образа!
```

## Правильный способ ✅

### Вариант 1: Полная пересборка (рекомендуется)

```bash
# 1. Загрузить все изменения
rsync -avz --exclude 'venv' --exclude '__pycache__' \
    /local/healthvault/ root@146.103.111.109:/root/healthvault/

# 2. Пересобрать Docker образ с нуля
ssh root@146.103.111.109 'cd /root/healthvault && docker-compose build --no-cache bot'

# 3. Пересоздать контейнеры с новым образом
ssh root@146.103.111.109 'cd /root/healthvault && docker-compose up -d'

# 4. Проверить
ssh root@146.103.111.109 'docker logs --tail 30 healthvault_bot'
```

### Вариант 2: Быстрая пересборка (быстрее, использует кэш)

```bash
# То же самое, но без --no-cache
ssh root@146.103.111.109 'cd /root/healthvault && docker-compose build bot && docker-compose up -d'
```

## Автоматизированный скрипт развёртывания

Используйте улучшенный скрипт `deploy.sh`:

```bash
#!/bin/bash
set -e

SERVER="root@146.103.111.109"
REMOTE_PATH="/root/healthvault"
SERVER_PASSWORD="SERVER_PASSWORD_REDACTED"

echo "🚀 Развёртывание HealthVault на продакшн..."

# 1. Загрузить код на сервер
echo "📤 Шаг 1/4: Загрузка кода..."
sshpass -p "$SERVER_PASSWORD" rsync -avz \
    --exclude 'venv' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git' \
    --exclude 'logs/*' \
    ./ ${SERVER}:${REMOTE_PATH}/

# 2. Пересобрать Docker образ (КРИТИЧНО для изменений кода!)
echo "🔨 Шаг 2/4: Пересборка Docker образа..."
sshpass -p "$SERVER_PASSWORD" ssh ${SERVER} \
    "cd ${REMOTE_PATH} && docker-compose build bot"

# 3. Перезапустить контейнеры с новым образом
echo "♻️ Шаг 3/4: Перезапуск контейнеров..."
sshpass -p "$SERVER_PASSWORD" ssh ${SERVER} \
    "cd ${REMOTE_PATH} && docker-compose up -d"

# 4. Проверить здоровье
echo "🏥 Шаг 4/4: Проверка развёртывания..."
sleep 3
sshpass -p "$SERVER_PASSWORD" ssh ${SERVER} \
    "docker logs --tail 20 healthvault_bot"

echo "✅ Развёртывание завершено!"
```

**Использование**:
```bash
chmod +x deploy.sh
./deploy.sh
```

## Быстрая справка

### Проверить дату кода в работающем контейнере

```bash
ssh root@146.103.111.109 'docker exec healthvault_bot ls -la /app/telegram-bot/handlers/photo.py'
```

Смотрите на дату файла - она должна совпадать с вашими недавними изменениями!

### Просмотр логов

```bash
# Последние 50 строк
ssh root@146.103.111.109 'docker logs --tail 50 healthvault_bot'

# Следить в реальном времени
ssh root@146.103.111.109 'docker logs -f healthvault_bot'

# Поиск ошибок
ssh root@146.103.111.109 'docker logs healthvault_bot 2>&1 | grep ERROR'
```

### Частые проблемы

#### Проблема: "Изменения кода не применяются"
**Причина**: Забыли пересобрать Docker образ  
**Решение**: Выполнить `docker-compose build bot && docker-compose up -d`

#### Проблема: "Контейнер постоянно перезапускается"
**Причина**: Синтаксическая ошибка или ошибка импорта в коде  
**Решение**: Проверить логи `docker logs healthvault_bot`

#### Проблема: "Ошибка подключения к базе данных"
**Причина**: Контейнер PostgreSQL не готов  
**Решение**: Проверить `docker-compose ps`, перезапустить при необходимости

## Разработка vs Продакшн

### Локальная разработка
- Изменения кода применяются сразу (без Docker)
- Запуск: `python telegram-bot/bot.py`

### Продакшн (Docker)
- Изменения кода требуют пересборки образа
- Лучшая изоляция и управление зависимостями
- Проще откатиться (использовать теги образов)

## Лучшие практики

1. **Всегда тестировать локально** перед развёртыванием
2. **Проверять логи сразу** после развёртывания
3. **Мониторить 5-10 минут** после деплоя
4. **Иметь план отката** (сохранить предыдущий образ)
5. **Документировать breaking changes** в commit messages

## Процедура отката

Если развёртывание что-то сломало:

```bash
# 1. Показать недавние образы
docker images healthvault-bot

# 2. Запустить предыдущую версию
docker tag healthvault-bot:previous healthvault-bot:latest
docker-compose up -d

# ИЛИ пересобрать из последнего рабочего коммита
git checkout <last-working-commit>
./deploy.sh
```

## Будущее улучшение: CI/CD

Рассмотреть настройку GitHub Actions для:
- ✅ Автозапуск тестов при push
- ✅ Автодеплой при слиянии в main
- ✅ Откат при провале health check
