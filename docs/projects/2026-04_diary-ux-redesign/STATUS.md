# Diary UX Redesign (Telegram Mini App)

**Status:** 🟢 COMPLETED
**Started:** 2026-04-19
**Owner:** Александр Лысковский
**Cohort:** all

## Цель

Редизайн экрана дневника питания: все 4 слота помещаются без скролла на iPhone (~700px), главное число (калории) — hero banner, чёткая иерархия, удобство одной рукой, таб-бар внизу.

## Что сделано

- Single-row header
- Large calorie hero banner
- Colored left-border meal slots
- Fiber + protein progress footer
- Warm Stone tab bar (Дневник live · Добавки stub · Настройки)
- Pure CSS/JS — без backend изменений
- Deploy через rsync → docker cp → Cloudflare cache purge

## Связи

- SPEC.md / PLAN.md
