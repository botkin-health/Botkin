# Настройка HealthVault на GitHub

## 📋 Быстрая инструкция

**См. подробную инструкцию в `GITHUB_SETUP.md`**

## Краткие шаги:

1. **Создайте репозиторий на GitHub:**
   - Перейдите: https://github.com/new
   - Название: `HealthVault`
   - Выберите **🔒 Private**
   - **НЕ** создавайте README, .gitignore или лицензию

2. **Подключите локальный репозиторий:**

```bash
cd /Users/alexlyskovsky/HealthVault
git remote add origin https://github.com/Lyskovsky/HealthVault.git
git branch -M main
git push -u origin main
```

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

