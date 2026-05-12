# Botkin User Guide (RU)

Пользовательский гайд для Botkin, собирается MkDocs с темой Material.

## Структура

```
docs/user_guide/ru/
├── mkdocs.yml          # конфиг MkDocs
├── docs/               # markdown-страницы
│   ├── index.md
│   ├── start.md
│   ├── commands.md
│   ├── dashboard.md
│   ├── mcp.md
│   ├── faq.md
│   └── changelog.md
├── README.md           # этот файл
└── DEPLOY.md           # инструкция деплоя на прод
```

## Локальный запуск

Требуется Python 3.9+.

```bash
cd docs/user_guide/ru
pip install mkdocs-material
mkdocs serve
```

Откроется на `http://127.0.0.1:8000/guide/`. Любая правка `*.md` или `mkdocs.yml` — live reload.

## Сборка

```bash
mkdocs build
```

Результат — в `docs/user_guide/ru/site/`. Эта папка статична: HTML + CSS + JS, можно отдавать любым веб-сервером.

## Деплой

См. [DEPLOY.md](DEPLOY.md).

## Правки

- Изменения текста — в `docs/*.md`.
- Изменения навигации, темы, шапки — в `mkdocs.yml`.
- Не коммитьте `site/` — это билд-артефакт (добавьте в `.gitignore`, если ещё не там).
