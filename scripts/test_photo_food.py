#!/usr/bin/env python3
"""
Проверка распознавания фото еды (в т.ч. Cola Zero 0 ккал).
Запуск: из корня репо
  python scripts/test_photo_food.py [путь/к/фото.png]
Если путь не указан — только проверка импортов и логики.
"""
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

def main():
    image_path = (Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    if not image_path or not image_path.exists():
        print("Укажи путь к фото: python scripts/test_photo_food.py <файл.png>")
        if image_path:
            print(f"Файл не найден: {image_path}")
        return 2

    from core.ocr_weight import parse_weight_screenshot
    from core.llm_router import analyze_message

    # 1) OCR весов не должен принять банку (вес 25–300 кг)
    weight_data = parse_weight_screenshot([image_path], api_key=None, description="")
    if weight_data:
        w = weight_data.get("weight")
        print(f"OCR весов вернул: weight={w} — фото уйдёт в 'весы', не в еду!")
        if w is not None and (w < 25 or w > 300):
            print("  (ожидаем: вес вне 25–300 кг не должен считаться весами)")
    else:
        print("OCR весов: не весы (ok — фото пойдёт в распознавание еды)")

    # 2) LLM должен вернуть food с КБЖУ (для Cola Zero — 0 ккал)
    result = analyze_message(text="Что на фото? Название продукта или блюда, вес и КБЖУ.", image_paths=[image_path])
    if not result:
        print("LLM вернул None — проверь ключи/сеть/лимиты")
        return 1
    t = result.get("type")
    print(f"LLM type={t}")
    if t == "food":
        data = result.get("data", {})
        tot = data.get("total_nutrition") or {}
        name = data.get("dish_name", "?")
        cal = tot.get("calories", 0)
        print(f"  dish_name={name}, calories={cal}")
        if cal == 0 and ("zero" in name.lower() or "cola" in name.lower()):
            print("  OK: распознан напиток с 0 ккал")
        elif cal is not None:
            print("  OK: есть калории")
    else:
        print(f"  Не еда — бот попросит описание. data={result.get('data')}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
