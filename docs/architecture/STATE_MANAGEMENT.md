# Архитектура управления состоянием

## Обзор

HealthVault бот использует собственную систему управления состоянием для отслеживания взаимодействий с пользователем через несколько сообщений (например, ожидание описания фото, диалоги подтверждения).

**Расположение**: `services/state.py`

## Основные концепции

### Класс UserState

```python
@dataclass
class UserState:
    user_id: str
    state: str  # например 'waiting_description', 'waiting_confirmation'
    data: Dict[str, Any]  # Гибкое хранилище для данных конкретного состояния
```

### State Manager

- **Singleton**: `state_manager` управляет всеми состояниями пользователей
- **Методы**:
  - `get_state(user_id)` - Получить текущее состояние пользователя
  - `set_state(user_id, state)` - Обновить состояние пользователя
  - `clear_state(user_id)` - Удалить состояние когда закончили

## Критический паттерн: Сохранение данных состояния

### ⚠️ Проблема

При пересоздании `UserState` легко случайно потерять существующие данные:

```python
# ❌ НЕПРАВИЛЬНО - menu_data теряется!
user_state = UserState(
    user_id=user_id,
    state='waiting_description',
    data={
        'photo_paths': photo_paths,
        'caption': caption,
        # menu_data отсутствует!
    }
)
```

### ✅ Решение

**ВСЕГДА** проверяйте существующие данные перед пересозданием состояния:

```python
# ✅ ПРАВИЛЬНО - сохраняем существующие данные
existing_menu_data = user_state.data.get('menu_data') if user_state else None

user_state = UserState(
    user_id=user_id,
    state='waiting_description',
    data={
        'photo_paths': photo_paths,
        'caption': caption,
        'menu_data': existing_menu_data,  # ✅ Сохранено!
    }
)
```

## Справочник полей данных состояния

### Обработка фото (`waiting_description`)

| Поле | Тип | Обязательно | Назначение |
|------|-----|-------------|------------|
| `photo_paths` | `List[str]` | Да | Пути к загруженным фото |
| `photo_file_ids` | `List[str]` | Да | Telegram file ID |
| `caption` | `str` | Нет | Текст подписи от пользователя |
| `menu_data` | `Dict` | Нет | **КРИТИЧНО**: Распознанные КБЖУ из изображения |

### Структура menu_data

```python
{
    'dish_name': str,         # Название блюда
    'calories': float,        # Общие калории
    'protein': float,         # Белки в граммах
    'fats': float,            # Жиры в граммах
    'carbs': float,           # Углеводы в граммах
    'weight': int,            # Вес порции в граммах (опционально)
    'nutrition_per_100g': {   # Значения на 100г (опционально)
        'calories': float,
        'protein': float,
        'fats': float,
        'carbs': float
    },
    'components': List[Dict], # Отдельные компоненты (опционально)
    'source': str             # Источник распознавания: 'chatgpt_vision', 'gemini_vision'
}
```

### Подтверждение приёма пищи (`waiting_confirmation`)

| Поле | Тип | Назначение |
|------|-----|------------|
| `description` | `str` | Описание приёма пищи от пользователя |
| `meal_items` | `List[Dict]` | Распознанные продукты |
| `meal_totals` | `Dict` | Суммарное КБЖУ |
| `meal_time` | `str` | Время приёма пищи (HH:MM) |
| `meal_name` | `str` | Название приёма (Завтрак, Обед и т.д.) |
| `date` | `str` | Дата если не сегодня (YYYY-MM-DD) |

## Лучшие практики

### 1. Всегда проверять существующее состояние

```python
user_state = state_manager.get_state(user_id)
if user_state:
    # Сохранить важные данные
    existing_menu_data = user_state.data.get('menu_data')
    existing_caption = user_state.data.get('caption')
```

### 2. Использовать helper-функции

Выносите создание состояния в переиспользуемые функции:

```python
def create_photo_state(
    user_id: str,
    photo_paths: List[Path],
    caption: str = None,
    menu_data: Dict = None,
    existing_state: UserState = None
) -> UserState:
    """
    Создать состояние обработки фото, сохраняя menu_data из existing_state.
    """
    final_menu_data = menu_data
    if not final_menu_data and existing_state:
        final_menu_data = existing_state.data.get('menu_data')
    
    return UserState(
        user_id=user_id,
        state='waiting_description',
        data={
            'photo_paths': [str(p) for p in photo_paths],
            'caption': caption or '',
            'menu_data': final_menu_data,
        }
    )
```

### 3. Добавить типизацию

Используйте Pydantic для валидации структуры данных:

```python
from pydantic import BaseModel

class PhotoStateData(BaseModel):
    photo_paths: List[str]
    caption: str = ''
    menu_data: Optional[Dict] = None  # IDE предупредит если забыли!
```

### 4. Очищать состояние когда закончили

```python
# После успешного сохранения
state_manager.clear_state(user_id)
```

## Типичные ошибки

### ❌ Создание нового состояния без проверки существующего

```python
# Это удалит все существующие данные!
user_state = UserState(user_id=user_id, state='new_state', data={})
```

### ❌ Предполагать что поля существуют

```python
# Может вызвать KeyError!
menu_data = user_state.data['menu_data']

# ✅ Использовать .get() с дефолтом
menu_data = user_state.data.get('menu_data')
```

### ❌ Изменять state.data напрямую

```python
# Изменения могут не сохраниться!
user_state.data['new_field'] = value

# ✅ Установить всё состояние целиком
data = user_state.data.copy()
data['new_field'] = value
user_state.data = data
state_manager.set_state(user_id, user_state)
```

## Тестирование state management

Всегда тестируйте сохранение состояния:

```python
def test_menu_data_preserved_on_state_update():
    # Создать начальное состояние с menu_data
    original_state = UserState(
        user_id='test',
        state='waiting_description',
        data={'menu_data': {'calories': 500}}
    )
    
    # Симулировать обновление состояния
    new_state = create_photo_state(
        user_id='test',
        photo_paths=[Path('/test.jpg')],
        existing_state=original_state
    )
    
    # menu_data должен сохраниться
    assert new_state.data['menu_data'] is not None
    assert new_state.data['menu_data']['calories'] == 500
```

## Отладка проблем с состоянием

Включите логирование состояния:

```python
logger.info(f"Текущее состояние: {user_state.state}")
logger.info(f"Ключи данных: {list(user_state.data.keys())}")
logger.info(f"menu_data присутствует: {user_state.data.get('menu_data') is not None}")
```

## Миграция на типизированное состояние (будущее)

Планируется миграция на Pydantic-based state management:

```python
class UserStateData(BaseModel):
    photo_paths: Optional[List[str]] = None
    caption: Optional[str] = None
    menu_data: Optional[MenuData] = None  # Типизировано!
    # ... другие поля
```

Это даст:
- ✅ Проверку типов на этапе компиляции
- ✅ Валидацию во время выполнения
- ✅ Автодополнение в IDE
- ✅ Самодокументирующийся код
