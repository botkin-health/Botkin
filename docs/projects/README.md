# Projects

Каждый многошаговый проект = отдельная папка `YYYY-MM_<slug>/` с обязательным `STATUS.md` и опциональными `SPEC.md`, `PLAN.md`, `RETRO.md`.

## Структура папки

```
YYYY-MM_<slug>/
├── STATUS.md   # ОБЯЗАТЕЛЬНО — текущий статус, цель, обновляется по ходу
├── SPEC.md     # дизайн-спека (что и почему)
├── PLAN.md     # task-by-task implementation план
└── RETRO.md    # пост-mortem / что узнали (после завершения)
```

## Статусы (в STATUS.md)

| Status | Значение |
|---|---|
| `🔵 ACTIVE` | В работе сейчас. Должно быть видно в ROADMAP NOW. |
| `🟢 COMPLETED` | Полностью реализовано, в проде. См. секцию DONE в ROADMAP. |
| `🟡 DEFERRED` | Отложено по решению (не выкинуто). С указанием условия возврата. |
| `🔴 REJECTED` | Отвергнуто. Не удалять — должна быть запись в `docs/architecture/decisions/` с причиной. |
| `⚪ PROPOSED` | Идея, до решения. Жди утверждения автора. |

## Шаблон STATUS.md

```markdown
# <название проекта>

**Status:** 🔵 ACTIVE | 🟢 COMPLETED | 🟡 DEFERRED | 🔴 REJECTED | ⚪ PROPOSED
**Started:** YYYY-MM-DD
**Target:** YYYY-MM-DD (если есть)
**Owner:** имя
**Cohort:** owner / family / early_user / all

## Цель
1-3 предложения.

## Текущее состояние
Что сделано, что в работе, что блокирует.

## Связи
- ADR: ../../architecture/decisions/NNNN-*.md
- PR'ы: #12, #13
- Документы: SPEC.md, PLAN.md
```

## Список проектов

| Период | Проект | Статус |
|---|---|---|
| 2026-05 | [server-side-sync](2026-05_server-side-sync/) | 🟢 COMPLETED |
| 2026-05 | [data-atlas](2026-05_data-atlas/) | 🟡 DEFERRED |
| 2026-04 | [share-dashboard](2026-04_share-dashboard/) | 🟢 COMPLETED |
| 2026-04 | [diary-ux-redesign](2026-04_diary-ux-redesign/) | 🟢 COMPLETED |
| 2026-04 | [nutrition-day-editor](2026-04_nutrition-day-editor/) | 🟢 COMPLETED |
| 2026-04 | [telegram-mini-app-settings](2026-04_telegram-mini-app-settings/) | 🟢 COMPLETED |

(Приватные дизайн-спеки от Sprint 1a/1b — в `~/FamilyHealth/_botkin_planning_private/`. См. ADR-0001.)
