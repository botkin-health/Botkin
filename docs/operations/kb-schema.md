# KB Schema — каноническое имя поля для биомаркеров

**Статус:** норма (с 2026-05-18). Менять только через PR с обоснованием.

## Правило одной строкой

Каждая запись об анализе (в секциях `blood_tests`, `biochemistry`, `hormones`, `vitamins`, `coagulogram`, `urine_tests`, `tumor_markers`, и т.д.) — содержит **словарь биомаркеров в поле `values`**, и только в нём.

```json
{
  "date": "2024-11-08",
  "lab": "spb_polyclinic_71",
  "values": {                      ← каноническое имя поля
    "hemoglobin_g_L": 154,
    "platelets_x10_9_L": 341,
    "glucose_mmol_L": 6.7
  }
}
```

## Что НЕ делать

❌ Не использовать `markers`, `biomarkers`, `results`, `data`, `analyses` как имя контейнера биомаркеров.
❌ Не вводить fallback типа `entry.get("values") or entry.get("markers")` — это «толерантный читатель», который скрывает баги.

## Что делать, если получил KB с другим именем

1. **Один раз** пройтись по файлу скриптом-миграцией (см. `scripts/import/migrate_kb_schema.py` или одноразовый Python в чате)
2. Обновить `_meta.schema_migration` в самом KB с датой и причиной
3. Запустить `kb_to_blood_tests.py` — он теперь падает с понятной ошибкой, если встретит `markers`

## История

| Дата | Что было | Что стало |
|---|---|---|
| 2026-05-18 | KB Андрея использовал `markers`, KB остальных — `values`. `kb_to_blood_tests.py` был «tolerant reader» с fallback | Андреев KB мигрирован на `values` (20 записей). Fallback убран. Скрипт падает с ValueError, если встречает `markers`. |

## Проверить инвариант локально

```bash
python3 -c "
import json, pathlib
base = pathlib.Path.home() / 'Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth'
for kb_path in base.glob('*/knowledge_base.json'):
    kb = json.loads(kb_path.read_text())
    bad = []
    def walk(o, path=''):
        if isinstance(o, dict):
            for k,v in o.items():
                if k == 'markers' and isinstance(v, dict):
                    bad.append(path+'.markers')
                walk(v, path+'.'+k)
        elif isinstance(o, list):
            for i,it in enumerate(o):
                walk(it, path+f'[{i}]')
    walk(kb)
    status = '✅' if not bad else '❌ ' + ', '.join(bad[:3])
    print(f'{status}  {kb_path.parent.name}')
"
```

Должно выводить `✅` для всех людей.
