# Архитектура HealthVault: База знаний vs Контекст чата

## 🎯 Ключевой принцип: **База знаний на диске = источник истины**

### 📁 Где хранятся данные:

1. **`knowledge_base.json`** - основная база знаний
   - Все медицинские анализы
   - История тестов
   - Структурированные данные
   - **Это источник истины!**

2. **`data/`** - файлы анализов
   - PDF файлы анализов
   - Извлеченные тексты
   - Медиа файлы

3. **`data/nutrition/nutrition_log.json`** - лог питания
   - Ежедневные записи питания
   - КБЖУ
   - История приемов пищи

4. **`data/analysis/`** - аналитические отчеты
   - Сравнительные анализы
   - Рекомендации
   - Динамика показателей

---

## 🔄 Как работает контекст:

### ❌ НЕ используем контекст чата как источник данных

**Контекст чата (окно Cursor) - это:**
- Временная память для текущей сессии
- Помощь в написании кода
- Обсуждение задач
- **НО НЕ хранилище данных!**

### ✅ Используем файлы на диске как источник истины

**При работе с данными:**
1. **Всегда читаем из файлов** (`knowledge_base.json`, `nutrition_log.json` и т.д.)
2. **Обновляем файлы** при изменении данных
3. **Коммитим в Git** для версионирования
4. **Контекст чата** используется только для обсуждения и помощи

---

## 💡 Пример: Корректировка питания с учетом анализов

### Сценарий: Нужно скорректировать питание на основе свежих анализов

#### ✅ Правильный подход:

```python
# 1. Читаем базу знаний с диска
import json
from pathlib import Path

knowledge_base = Path("knowledge_base.json")
with open(knowledge_base, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 2. Находим свежие анализы
latest_tests = [test for test in data['blood_tests'] 
                if test.get('status') != 'historical']
latest_test = max(latest_tests, key=lambda x: x['date'])

# 3. Анализируем показатели
cholesterol = latest_test.get('values', {}).get('cholesterol')
ldl = latest_test.get('values', {}).get('LDL')

# 4. Читаем текущее питание
nutrition_log = Path("data/nutrition/nutrition_log.json")
with open(nutrition_log, 'r', encoding='utf-8') as f:
    nutrition = json.load(f)

# 5. Генерируем рекомендации на основе данных
if ldl and ldl > 3.0:
    recommendations = {
        "reduce_saturated_fats": True,
        "increase_fiber": True,
        "omega3_supplement": True
    }
    
# 6. Сохраняем рекомендации в файл
recommendations_file = Path("data/analysis/nutrition_recommendations.json")
with open(recommendations_file, 'w', encoding='utf-8') as f:
    json.dump(recommendations, f, ensure_ascii=False, indent=2)
```

#### ❌ Неправильный подход:

```python
# НЕ делаем так:
# "Помни, у меня холестерин 5.66" - это в контексте чата
# "Вчера я ел..." - это в контексте чата

# Вместо этого:
# Всегда читаем из knowledge_base.json и nutrition_log.json
```

---

## 🔧 Работа с общим контекстом

### Когда использовать разные чаты:

#### 1. **Текущий чат (общий)**
- ✅ Обработка новых анализов
- ✅ Обновление базы знаний
- ✅ Создание аналитических отчетов
- ✅ Работа с файлами на диске

#### 2. **Чат "бот"** (если есть)
- ✅ Разработка телеграм-бота
- ✅ Обработка сообщений от пользователя
- ✅ Интеграция с API

#### 3. **Чат "сон"** (если есть)
- ✅ Анализ данных сна
- ✅ Обработка данных из SleepCycle
- ✅ Специфичные для сна задачи

### Как работать с общим контекстом:

#### ✅ Правильно:

1. **Читаем данные из файлов:**
   ```bash
   # В любом чате
   cat knowledge_base.json | jq '.blood_tests[-1]'
   ```

2. **Обновляем файлы:**
   ```python
   # В любом чате
   # Обновляем knowledge_base.json
   # Коммитим в Git
   ```

3. **Используем контекст чата для обсуждения:**
   - "Посмотри на последние анализы в knowledge_base.json"
   - "Сравни с летними анализами 2024-07-12"
   - "Создай рекомендации по питанию"

#### ❌ Неправильно:

1. **Не полагаемся на память чата:**
   - "Помни, у меня был холестерин 5.66" ❌
   - Вместо: "Читай из knowledge_base.json" ✅

2. **Не храним данные в контексте:**
   - "Сохрани это в памяти чата" ❌
   - Вместо: "Сохрани в knowledge_base.json" ✅

---

## 📊 Пример: Корректировка питания с учетом анализов

### Шаг 1: Читаем свежие анализы

```python
# scripts/analyze_nutrition_from_tests.py
import json
from pathlib import Path
from datetime import datetime

def get_latest_blood_tests():
    """Получает последние анализы крови из базы знаний"""
    kb_path = Path("knowledge_base.json")
    with open(kb_path, 'r', encoding='utf-8') as f:
        kb = json.load(f)
    
    # Фильтруем только свежие (не исторические)
    fresh_tests = [t for t in kb['blood_tests'] 
                   if t.get('status') != 'historical']
    
    # Сортируем по дате, берем последний
    if fresh_tests:
        latest = max(fresh_tests, key=lambda x: x['date'])
        return latest
    return None

def get_current_nutrition():
    """Получает текущее питание"""
    nutrition_path = Path("data/nutrition/nutrition_log.json")
    if nutrition_path.exists():
        with open(nutrition_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def generate_nutrition_recommendations(test_data, nutrition_data):
    """Генерирует рекомендации по питанию на основе анализов"""
    recommendations = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "based_on_test": test_data.get('date'),
        "recommendations": []
    }
    
    values = test_data.get('values', {})
    
    # Анализ холестерина
    if 'LDL' in values and values['LDL']:
        ldl = values['LDL']
        if ldl > 3.0:
            recommendations['recommendations'].append({
                "type": "reduce_ldl",
                "priority": "high",
                "actions": [
                    "Уменьшить насыщенные жиры",
                    "Увеличить клетчатку (овощи, цельнозерновые)",
                    "Добавить омега-3 (рыба, льняное масло)",
                    "Ограничить красное мясо"
                ]
            })
    
    # Анализ витамина D
    if 'vitamin_d' in values and values['vitamin_d']:
        vit_d = values['vitamin_d']
        if vit_d < 30:
            recommendations['recommendations'].append({
                "type": "increase_vitamin_d",
                "priority": "medium",
                "actions": [
                    "Добавить добавку витамина D (2000-4000 МЕ/день)",
                    "Увеличить потребление жирной рыбы",
                    "Больше времени на солнце"
                ]
            })
    
    return recommendations

# Использование
if __name__ == "__main__":
    test = get_latest_blood_tests()
    nutrition = get_current_nutrition()
    
    if test:
        recs = generate_nutrition_recommendations(test, nutrition)
        
        # Сохраняем рекомендации
        output_path = Path("data/analysis/nutrition_recommendations.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(recs, f, ensure_ascii=False, indent=2)
        
        print("✅ Рекомендации сохранены в data/analysis/nutrition_recommendations.json")
    else:
        print("⚠️  Свежие анализы не найдены")
```

### Шаг 2: Применяем рекомендации

```python
# В любом чате можно использовать:
# "Прочитай рекомендации из data/analysis/nutrition_recommendations.json"
# "Обнови мой план питания с учетом этих рекомендаций"
```

---

## 🎯 Резюме

### ✅ Делай так:

1. **Всегда читай из файлов** (`knowledge_base.json`, `nutrition_log.json`)
2. **Обновляй файлы** при изменении данных
3. **Используй контекст чата** для обсуждения и помощи
4. **Коммить в Git** для версионирования

### ❌ Не делай так:

1. **Не полагайся на память чата** для хранения данных
2. **Не храни данные в контексте** вместо файлов
3. **Не дублируй данные** между чатами

### 🔑 Ключевое правило:

> **База знаний на диске (и в GitHub) - это источник истины.  
> Контекст чата - это инструмент для работы с этой базой знаний.**

---

*Документ создан: 2026-01-07*


