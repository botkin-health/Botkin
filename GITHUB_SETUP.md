# Настройка HealthVault на GitHub

## Текущая ситуация

- ✅ **FamilyDocs** → подключен к `https://github.com/Lyskovsky/FamilyDocuments.git`
- ⏳ **HealthVault** → нужно создать новый репозиторий на GitHub

## Шаги для создания репозитория HealthVault на GitHub

### 1. Создайте новый репозиторий на GitHub

1. Перейдите на: https://github.com/new
2. **Repository name**: `HealthVault`
3. **Description**: `Personal health knowledge base - анализы, спорт, образ жизни`
4. **Visibility**: Выберите **🔒 Private** (приватный!)
5. **НЕ** ставьте галочки на:
   - ❌ Add a README file (у нас уже есть)
   - ❌ Add .gitignore (у нас уже есть)
   - ❌ Choose a license (не нужно)

6. Нажмите **"Create repository"**

### 2. Подключите локальный репозиторий к GitHub

После создания репозитория на GitHub, выполните:

```bash
cd /Users/alexlyskovsky/HealthVault
git remote add origin https://github.com/Lyskovsky/HealthVault.git
git branch -M main
git push -u origin main
```

### 3. Проверка

После выполнения команд проверьте:

```bash
git remote -v
# Должно показать:
# origin  https://github.com/Lyskovsky/HealthVault.git (fetch)
# origin  https://github.com/Lyskovsky/HealthVault.git (push)
```

## Итоговая структура репозиториев

После настройки у вас будет:

- **FamilyDocuments** (`github.com/Lyskovsky/FamilyDocuments`)
  - Локально: `/Users/alexlyskovsky/FamilyDocs`
  - Содержит: документы семьи, паспорта, репатриация

- **HealthVault** (`github.com/Lyskovsky/HealthVault`)
  - Локально: `/Users/alexlyskovsky/HealthVault`
  - Содержит: здоровье, анализы, спорт, образ жизни

## Важно!

⚠️ **Два разных проекта = два разных репозитория на GitHub**

Это правильный подход, потому что:
- Разные темы (документы vs здоровье)
- Разная структура данных
- Разные права доступа (если понадобится)
- Легче управлять и искать информацию

