#!/usr/bin/env python3
"""
LLM Prompt E2E тестер — проверяет реальные ответы GPT/Gemini.

Используется для верификации фиксов промпта без отправки в Telegram.
Можно запустить:
  - Локально: python scripts/test_llm_prompt.py
  - На сервере: docker exec healthvault_bot python /app/scripts/test_llm_prompt.py
  - После деплоя в pipeline: ./deploy.sh && docker exec healthvault_bot python /app/scripts/test_llm_prompt.py

Если тест не прошёл — бот НЕ перезапускается, нужно смотреть результат.
"""

import sys
import json
import argparse
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.llm_router import analyze_message

# ============================================================
# 📋 ТЕСТ-КЕЙСЫ
# Добавляй новые кейсы сюда при каждом фиксе промпта.
# Формат:
#   name       — название теста (для отчёта)
#   text       — текст сообщения пользователя
#   photo      — путь к фото (опционально, только если запускаешь на сервере)
#   expect_type — ожидаемый тип ответа ("food", "vitamins", "weight", "other")
#   calories   — (min, max) диапазон ожидаемых калорий, или None если не важно
#   bad_value  — значение которое БЫЛО до фикса (для регрессии), или None
#   tags       — список тегов для фильтрации (например ["label", "regression"])
# ============================================================

TEST_CASES = [
    # ----------------------------------------------------------
    # ГРУППА 1: Этикетки "на 100г" с указанием веса пользователем
    # Регрессия: баг Ники — индейка 150г возвращала 169 ккал (per-100g) вместо 253.5
    # ----------------------------------------------------------
    {
        "name": "Этикетка на 100г × вес пользователя [регрессия: индейка 150г]",
        "tags": ["label", "regression", "per-100g"],
        "text": (
            "Консервы индейки томлёная в собственном соку, "
            "этикетка на 100г: белки 18.5г, жиры 10.5г, 169 ккал. "
            "Вес порции: 150 грамм"
        ),
        "expect_type": "food",
        "calories": (200, 310),  # 169 * 1.5 = 253.5
        "bad_value": 169,        # per-100g значение — не должно быть итогом
        "notes": "Если вернул ~169 — промпт не умножает на вес. Ожидается ~253.5 ккал.",
    },
    {
        "name": "Этикетка на 100г × 100г (без указания веса = default 100г)",
        "tags": ["label", "per-100g"],
        "text": (
            "Протеин на этикетке: белки 70г, жиры 8г, углеводы 12г, 400 ккал на 100г. "
            "Порция не указана."
        ),
        "expect_type": "food",
        "calories": (350, 450),  # дефолт 100г — значения с этикетки
        "bad_value": None,
        "notes": "Без уточнения веса — берём 100г (значения с этикетки напрямую).",
    },

    # ----------------------------------------------------------
    # ГРУППА 2: Карточки блюд с ЯВНЫМИ итоговыми значениями (не на 100г)
    # Эти значения должны браться AS-IS
    # ----------------------------------------------------------
    {
        "name": "Карточка блюда с итоговыми ккал (не на 100г)",
        "tags": ["label", "explicit-total"],
        "text": "Пицца Маргарита, порция 300г. Итого: 668 ккал, белки 28г, жиры 22г, углеводы 82г.",
        "expect_type": "food",
        "calories": (620, 720),  # должно быть ~668, не умножать ни на что
        "bad_value": None,
        "notes": "Явный итог — брать без умножений.",
    },

    # ----------------------------------------------------------
    # ГРУППА 3: Базовые smoke-тесты чтобы убедиться что не сломали что-то другое
    # ----------------------------------------------------------
    {
        "name": "Простой текст: гречка 200г",
        "tags": ["smoke"],
        "text": "гречка 200г",
        "expect_type": "food",
        "calories": (600, 850),
        "bad_value": None,
        "notes": "Гречка: ~340 ккал/100г × 2 = ~680 ккал.",
    },
    {
        "name": "Витамины: омега-3",
        "tags": ["smoke", "vitamins"],
        "text": "принял омегу 3",
        "expect_type": "vitamins",
        "calories": None,
        "bad_value": None,
        "notes": "Должен распознать как витамины, не еда.",
    },
    {
        "name": "Стандартная порция без веса: борщ",
        "tags": ["smoke", "standard-portion"],
        "text": "борщ на обед",
        "expect_type": "food",
        "calories": (80, 200),  # стандартная порция борща ~300г, ~120 ккал
        "bad_value": None,
        "notes": "Без веса — LLM должен взять стандартную порцию из базы (~300г).",
    },
    {
        "name": "Нулевые калории: кола-зеро",
        "tags": ["smoke", "zero-calorie"],
        "text": "Coca-Cola Zero 330 мл",
        "expect_type": "food",
        "calories": (-1, 5),   # должно быть 0, разрешаем погрешность до 5
        "bad_value": None,
        "notes": "Zero-calorie напиток — должен вернуть 0 ккал.",
    },
]


def run_tests(tags_filter=None, stop_on_fail=False, verbose=False):
    """Запускает тест-кейсы и возвращает (passed, failed, total)."""

    cases = TEST_CASES
    if tags_filter:
        cases = [tc for tc in TEST_CASES if any(t in tc.get("tags", []) for t in tags_filter)]

    passed = 0
    failed = 0

    print("=" * 65)
    print("🧪  LLM Prompt E2E Tests")
    if tags_filter:
        print(f"    Фильтр тегов: {tags_filter}")
    print("=" * 65)

    for tc in cases:
        name = tc["name"]
        text = tc["text"]
        photo = tc.get("photo")
        expected_type = tc.get("expect_type", "food")
        cal_range = tc.get("calories")
        bad_value = tc.get("bad_value")
        notes = tc.get("notes", "")

        print(f"\n📋 {name}")
        if verbose:
            print(f"   Запрос: {text[:100]}...")

        # Вызов LLM
        try:
            image_paths = [photo] if photo and Path(photo).exists() else None
            result = analyze_message(text=text, image_paths=image_paths)
        except Exception as e:
            print(f"   ❌ FAIL: исключение при вызове LLM: {e}")
            failed += 1
            if stop_on_fail:
                break
            continue

        if not result:
            print(f"   ❌ FAIL: LLM вернул None (API недоступен / нет баланса)")
            failed += 1
            if stop_on_fail:
                break
            continue

        actual_type = result.get("type")
        data = result.get("data", {})

        # Проверка типа
        if actual_type != expected_type:
            print(f"   ❌ FAIL: тип '{actual_type}' ≠ '{expected_type}'")
            failed += 1
            if stop_on_fail:
                break
            continue

        # Для еды — проверяем калории
        if expected_type == "food" and cal_range is not None:
            total = data.get("total_nutrition") or {}
            items = data.get("items", [])
            calories = total.get("calories") or sum(
                (i.get("calories") or 0) for i in items
            )
            protein = (total.get("protein") or
                       sum((i.get("protein") or 0) for i in items))

            cal_min, cal_max = cal_range

            if verbose:
                print(f"   Ответ LLM: {data.get('dish_name')} — {calories} ккал, Б:{protein}")
                if verbose and data.get("items"):
                    for item in data["items"][:3]:
                        print(f"     · {item.get('name')} {item.get('weight')}г → {item.get('calories')} ккал")

            # Регрессия: не должно быть именно bad_value
            if bad_value is not None and abs(calories - bad_value) < 5:
                print(
                    f"   ❌ REGRESSION: вернул {calories} ккал — "
                    f"это per-100g значение ({bad_value}), промпт не умножает!"
                )
                if notes:
                    print(f"   ℹ  {notes}")
                failed += 1
                if stop_on_fail:
                    break
                continue

            if cal_min <= calories <= cal_max:
                print(f"   ✅ PASS — {calories} ккал ∈ [{cal_min}, {cal_max}]")
                passed += 1
            else:
                print(f"   ❌ FAIL — {calories} ккал ∉ [{cal_min}, {cal_max}]")
                if notes:
                    print(f"   ℹ  {notes}")
                failed += 1
                if stop_on_fail:
                    break
        else:
            # Для витаминов/веса — достаточно правильного типа
            print(f"   ✅ PASS — тип '{actual_type}' корректен")
            passed += 1

    print("\n" + "=" * 65)
    total = len(cases)
    emoji = "🎉" if failed == 0 else "💥"
    print(f"{emoji}  Итого: {passed}/{total} passed, {failed} failed")
    print("=" * 65)
    return passed, failed, total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM Prompt E2E тесты")
    parser.add_argument("--tags", nargs="+", help="Запустить только тесты с этими тегами (напр: --tags regression label)")
    parser.add_argument("--stop-on-fail", action="store_true", help="Остановиться при первом падении")
    parser.add_argument("--verbose", "-v", action="store_true", help="Детальный вывод LLM-ответов")
    args = parser.parse_args()

    passed, failed, total = run_tests(
        tags_filter=args.tags,
        stop_on_fail=args.stop_on_fail,
        verbose=args.verbose,
    )
    sys.exit(0 if failed == 0 else 1)
