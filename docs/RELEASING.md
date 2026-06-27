# Релизы Botkin

Версии — **SemVer** (`MAJOR.MINOR.PATCH`). Сейчас pre-stable (`0.x.y`).
До `1.0.0` API/схема БД может меняться без предупреждения.

## Когда какую цифру

| Часть | Бампать когда | Примеры |
|---|---|---|
| **PATCH** (0.5.0 → 0.5.**1**) | Багфиксы, без новых фич | Hotfix webhook; парсер sleep; опечатка в /help |
| **MINOR** (0.5.0 → 0.**6**.0) | Новая фича, обратно-совместимо | Команда `/share`; ApoB на дашборде; MCP-сервер |
| **MAJOR** (**1**.0.0) | Breaking changes | Смена схемы БД без миграции; реверс публичного API |

## Single source of truth

- `core/_version.py` — `__version__ = "X.Y.Z"`, читает `bot.py`
- `pyproject.toml` — `version = "X.Y.Z"` для pip/build-инструментов
- `docs/landing/index.html` — текст «Botkin vX.Y.Z» в pill и footer

**Не редактируй руками** — используй `scripts/bump_version.py`:

```bash
python3 scripts/bump_version.py 0.5.1
```

Скрипт обновит все три места сразу.

## Релизный workflow

```bash
# 1. Закончили работу в main (PR'ы смержены, тесты зелёные)
# 2. Решили: это патч / minor / major
# 3. Бампим
python3 scripts/bump_version.py 0.5.1

# 4. Коммитим и тегим
git diff   # проверить
git commit -am "release: v0.5.1"
git tag -a v0.5.1 -m "Webhook auto-register + brand cleanup"
git push && git push --tags

# 5. GitHub Release (опционально)
gh release create v0.5.1 --notes "..."

# 6. Деплой бота — только через GitHub Actions «Deploy prod»
gh workflow run deploy-prod.yml -f branch=main   # бот (собирает образ → GHCR → pull на сервере)
rsync -avz --exclude='._*' docs/landing/ \
      root@116.203.213.137:/opt/botkin-site/      # лендинг
```

## История версий

| Версия | Дата | Что |
|---|---|---|
| `v0.4.0` | 2026-05-12 | Ретроактивно: ребрендинг HealthVault → Botkin, лендинг botkin.health, mkdocs гайд |
| `v0.5.0` | 2026-05-12 | Webhook auto-register, чистка остатков бренда HealthVault, SemVer + bump-скрипт |

---

[← Документация Botkin — Index](INDEX.md)
