# Настройка HealthVault на GitHub

## Шаги для создания репозитория на GitHub

1. **Создайте новый репозиторий на GitHub:**
   - Перейдите на https://github.com/new
   - Название: `HealthVault`
   - Описание: "Personal health knowledge base"
   - Выберите **Private** (приватный репозиторий)
   - **НЕ** создавайте README, .gitignore или лицензию (они уже есть)

2. **Подключите локальный репозиторий к GitHub:**

```bash
cd /Users/alexlyskovsky/HealthVault
git remote add origin https://github.com/YOUR_USERNAME/HealthVault.git
git branch -M main
git push -u origin main
```

Замените `YOUR_USERNAME` на ваш GitHub username.

## Проверка текущего состояния

```bash
# Проверить статус
cd /Users/alexlyskovsky/HealthVault
git status

# Посмотреть структуру проекта
ls -la
```

## Важно помнить

- **HealthVault** находится в `/Users/alexlyskovsky/HealthVault`
- **FamilyDocs** находится в `/Users/alexlyskovsky/FamilyDocs`
- Это два разных проекта с разными репозиториями

