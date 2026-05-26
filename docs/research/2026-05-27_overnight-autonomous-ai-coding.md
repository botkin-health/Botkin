# Research: Ночные автономные задачи для AI-кодинг агентов

Дата: 2026-05-27 · По запросу: «Что опытные vibe coders запускают overnight/фоново?»

---

## TL;DR

- **Claude Code Routines** (запущены в Q1 2026) — это официальный способ запускать агента по расписанию или по событию на инфраструктуре Anthropic (без локального компа). Pro: 5 рутин/день, Max: 15/день.
- **Топ задачи overnight**: фикс багов из трекера + черновой PR, проверка документации на drift, dependency upgrades, генерация тестов, dead code removal (vulture + AI).
- **Главная ловушка**: context window overflow убивает длинные сессии — решение через `command > log.log; tail -20 log.log` и STATUS.md handoff-документы между фазами.
- **Python-стек серьёзных проектов**: Ruff (fast lint) + mypy --strict + bandit (security) + vulture (dead code) + mutmut (mutation testing, запускать только overnight — долго) + semgrep.
- **Практический паттерн**: ночью агент не «пишет фичи», а чинит технический долг — тесты, типы, безопасность, документация. Фичи — днём, под присмотром.

---

## Контекст

Botkin — Python-проект на aiogram + PostgreSQL с растущим кодом. Проекту ~4.5 месяца, и уже накопился технический долг: нет mypy strict, нет mutation testing, нет автоматических security-сканов. Ночные агентные рутины — способ гасить этот долг без затрат внимания разработчика.

---

## Что конкретно запускают overnight

### Категория 1: Bug fixing + PR drafts
**Паттерн (из Claude Code Routines docs):**
```
Каждую ночь в 2:00: взять топ-баг из Linear/GitHub Issues,
попробовать исправить, открыть draft PR.
```
Devin специально позиционируется для этого: «работает 30 мин — несколько часов, открывает PR, присылает нотификацию». Хорошо работает для: dependency upgrades, migration tasks, bulk refactoring.

### Категория 2: Documentation drift
**Паттерн (официальный пример Anthropic):**
```
Еженедельно: найти все PR за 7 дней, проверить какие функции изменились,
проверить документацию на актуальность, открыть PR с правками.
```

### Категория 3: Dead code removal
Codegen.com описывает pipeline: vulture → список кандидатов → AI генерирует PR на удаление.
Статья «I Used an AI Agent to Delete 5,000 Lines of Dead Code» (Medium) — реальный кейс.

### Категория 4: Test generation
Overnight: находить функции без покрытия, генерировать unit-тесты, добавлять в PR.
Один разработчик отчитался: агент overnight написал 477 строк утилитного кода и 42 теста.

### Категория 5: Security / compliance scan
Semgrep + Bandit overnight → issue list → опциональный auto-fix PR для очевидных проблем.

---

## Как не сломать длинную сессию (паттерн от Eva Khmelinskaya, Medium)

**Проблема:** context window заполняется stdout/stderr инструментов.

**Решения:**
1. В CLAUDE.md прописать: `всегда перенаправляй вывод: command > log.log 2>&1; tail -20 log.log`
2. **STATUS.md handoff**: в конце каждой фазы (30-60 мин) — записать статус, следующие шаги, ключевые метрики. Новая фаза начинается с чистого контекста.
3. Разбивать задачу на фазы с явным `/goal` — агент сам знает когда остановиться.

**Паттерн deadline-based (Stark Insider):**
```
"работай блоками, проверяй реальное время сервера,
продолжай до 11:10 AM — не останавливайся и не задавай вопросов"
```

---

## Python static analysis — стек серьёзных проектов

| Инструмент | Что делает | Когда запускать | Скорость |
|---|---|---|---|
| **Ruff** | lint + format (заменяет flake8/isort/black) | pre-commit + CI (мс) | 10-100x быстрее flake8 |
| **mypy --strict** | типы строго | CI on PR | медленно, но критично |
| **Pyright** | альтернатива mypy, лучше на больших базах | CI on PR | быстрее mypy |
| **bandit** | security (SQL injection, hardcoded secrets) | CI + overnight | быстро |
| **semgrep** | кастомные security паттерны | CI + overnight | быстро |
| **vulture** | dead code (неиспользуемые функции/импорты) | overnight или weekly | быстро |
| **mutmut** | mutation testing (качество тестов) | только overnight | МЕДЛЕННО (часы) |
| **radon** | complexity metrics (cyclomatic complexity) | weekly | быстро |
| **prospector** | агрегатор: pyflakes + pycodestyle + dodgy + mypy | overnight | средне |

**mutmut подробнее:** запускать `mutmut run` overnight — создаёт «мутации» в коде и проверяет убивают ли их тесты. Если тест не замечает мутацию — тест слабый. Версия 3.5.0 (февраль 2026). На 50k LOC занимает часы, в CI запускать только scheduled, не на каждый PR.

---

## Инструменты и ресурсы

### Claude Code Routines
- [Официальная документация](https://code.claude.com/docs/en/routines)
- [Announcing routines](https://claude.com/blog/introducing-routines-in-claude-code)
- [Практический гайд (Better Stack)](https://betterstack.com/community/guides/ai/claude-code-routines/)

### Overnight execution паттерны
- [Running Claude Code Autonomously Overnight — What Breaks](https://medium.com/@evekhm/running-claude-code-autonomously-overnight-what-breaks-and-how-to-fix-it-3bee3bd958b5) — лучшая статья по практике
- [Claude Code Time Hack (Stark Insider)](https://www.starkinsider.com/2026/05/claude-code-autonomous-coding-time-hack.html)
- [I Tried to Run an AI Coding Agent Overnight](https://brianfischman.medium.com/i-tried-to-run-an-ai-coding-agent-overnight-heres-what-actually-happened-f97288b7be35)

### Static analysis
- [python-linters-and-code-analysis (vintasoftware)](https://github.com/vintasoftware/python-linters-and-code-analysis) — curated list
- [analysis-tools.dev/tag/python](https://analysis-tools.dev/tag/python) — 135 инструментов
- [mutmut на PyPI](https://pypi.org/project/mutmut/)
- [Automating Dead Code Removal (Codegen)](https://codegen.com/automating-dead-code-removal-with-ai-and-static-analysis/)

---

## Предупреждение про стоимость

Задокументированный кейс: разработчик оставил Claude Code overnight → $6,000 за токены ([makeuseof.com](https://www.makeuseof.com/someone-left-claude-code-running-overnight-and-it-cost-6000/)). Claude Code Auto Mode (Q1 2026) добавил Human Approval Gates — обязательно включать для длинных сессий. Routines на инфраструктуре Anthropic потребляют кредиты из плана.

---

## Рекомендация для Botkin

**Начать с этого** (в порядке приоритета):

1. **Ruff** — добавить в pre-commit hook прямо сейчас (5 минут, высокая отдача)
2. **mypy --strict** — добавить в CI, начать с `--ignore-missing-imports`, постепенно ужесточать
3. **bandit** — в CI на каждый PR, критично для проекта с медданными
4. **Claude Code Routine: еженедельный dead code scan** — vulture → список в GitHub Issue, опционально авто-PR
5. **mutmut** — запускать вручную раз в месяц overnight пока тестов мало, потом в scheduled CI

**Не трогать пока:** Devin (дорого для домашнего проекта), prospector (избыточен при Ruff+mypy).

---

## Следующие шаги для Botkin

- [ ] Добавить `ruff` в `.pre-commit-config.yaml` + `pyproject.toml`
- [ ] Добавить `mypy --ignore-missing-imports` в `Makefile` и CI
- [ ] Добавить `bandit -r telegram-bot/ scripts/` в CI pipeline
- [ ] Создать Claude Code Routine: еженедельный `vulture . --min-confidence 80` → GitHub Issue
- [ ] Добавить в CLAUDE.md: правило `command > log.log 2>&1; tail -20 log.log` для длинных задач
- [ ] Создать `STATUS.md` шаблон для handoff между агентными сессиями
