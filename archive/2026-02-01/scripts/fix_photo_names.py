#!/usr/bin/env python3
from pathlib import Path
import shutil

path = Path('/Users/alexlyskovsky/HealthVault/data/media/body-photos')

# На основе визуального анализа изображений:
# body_photo_front_2026-01-08.jpeg -> боковой вид слева -> должен быть left
# body_photo_left_2026-01-08.jpeg -> фронтальный вид -> должен быть front
# body_photo_right_2026-01-08.jpeg -> оставляем как есть (пока)

print("🔄 Переименование файлов...")

# Шаг 1: Переименовываем во временные имена
old_front = path / "body_photo_front_2026-01-08.jpeg"
old_left = path / "body_photo_left_2026-01-08.jpeg"
old_right = path / "body_photo_right_2026-01-08.jpeg"

temp1 = path / "temp_1_rename.jpeg"
temp2 = path / "temp_2_rename.jpeg"
temp3 = path / "temp_3_rename.jpeg"

if old_front.exists():
    old_front.rename(temp1)
    print(f"✅ {old_front.name} → temp1")
if old_left.exists():
    old_left.rename(temp2)
    print(f"✅ {old_left.name} → temp2")
if old_right.exists():
    old_right.rename(temp3)
    print(f"✅ {old_right.name} → temp3")

# Шаг 2: Переименовываем в правильные имена
# temp2 (бывший left, который фронтальный) -> front
# temp1 (бывший front, который боковой слева) -> left
# temp3 (бывший right) -> right

new_front = path / "body_photo_front_2026-01-08.jpeg"
new_left = path / "body_photo_left_2026-01-08.jpeg"
new_right = path / "body_photo_right_2026-01-08.jpeg"

if temp2.exists():
    temp2.rename(new_front)
    print(f"✅ temp2 → {new_front.name} (фронтальный)")
if temp1.exists():
    temp1.rename(new_left)
    print(f"✅ temp1 → {new_left.name} (боковой слева)")
if temp3.exists():
    temp3.rename(new_right)
    print(f"✅ temp3 → {new_right.name} (боковой справа)")

print("\n✅ Переименование завершено!")
