#!/usr/bin/env python3
"""
Интеграционные тесты для предотвращения регрессии бага с потерей menu_data.

Эти тесты проверяют что КБЖУ не теряется при пересоздании состояния.
"""

import pytest
from pathlib import Path
from typing import Dict
from services.state import UserState, StateManager
from services.state_helpers import (
    create_photo_state,
    update_state_menu_data,
    get_menu_data_from_state,
    preserve_and_merge_state_data
)
from services.state_models import MenuData


@pytest.fixture
def sample_menu_data() -> Dict:
    """Тестовые данные меню (Elementaree рецепт)."""
    return {
        'dish_name': 'Рыбные кебабы с гарниром из зелёного горошка',
        'calories': 500.0,
        'protein': 33.0,
        'fats': 13.0,
        'carbs': 61.0,
        'weight': 415,
        'source': 'chatgpt_vision'
    }


@pytest.fixture
def state_manager():
    """Свежий state manager для каждого теста."""
    return StateManager()


class TestMenuDataPreservation:
    """Тесты для проверки сохранения menu_data при пересоздании состояния."""
    
    def test_menu_data_preserved_when_state_recreated(
        self, 
        state_manager, 
        sample_menu_data
    ):
        """
        РЕГРЕССИОННЫЙ ТЕСТ для бага с потерей menu_data.
        
        Сценарий:
        1. Пользователь отправляет фото Elementaree карточки
        2. ChatGPT распознаёт КБЖУ (500 ккал)
        3. Пользователь добавляет caption "ужин"
        4. Состояние п��ресоздаётся для обработки caption
        5. БАГ (БЫЛО): menu_data терялся
        6. ИСПРАВЛЕНО: menu_data сохраняется
        """
        user_id = "test_user_123"
        
        # ШАГ 1: Создать начальное состояние с menu_data (после распознавания)
        initial_state = UserState(
            user_id=user_id,
            state='waiting_description',
            data={
                'photo_paths': ['/tmp/test_photo.jpg'],
                'photo_file_ids': ['file_123'],
                'menu_data': sample_menu_data
            }
        )
        state_manager.set_state(user_id, initial_state)
        
        # Проверить что menu_data на месте
        assert initial_state.data['menu_data'] is not None
        assert initial_state.data['menu_data']['calories'] == 500.0
        
        # ШАГ 2: Пересоздать состояние (симуляция обработки caption)
        # Это то место где БЫЛ БАГ
        existing_state = state_manager.get_state(user_id)
        new_state = create_photo_state(
            user_id=user_id,
            photo_paths=[Path('/tmp/test_photo.jpg')],
            photo_file_ids=['file_123'],
            caption='ужин',
            menu_data=None,  # ← НЕ передаём menu_data явно
            existing_state=existing_state  # ← Должен взять menu_data отсюда
        )
        
        # ПРОВЕРКА: menu_data ДОЛЖЕН СОХРАНИТЬСЯ
        assert new_state.data['menu_data'] is not None, \
            "КРИТИЧЕСКИЙ БАГ: menu_data потерян при пересоздании состояния!"
        
        assert new_state.data['menu_data']['dish_name'] == \
            'Рыбные кебабы с гарниром из зелёного горошка'
        assert new_state.data['menu_data']['calories'] == 500.0
        assert new_state.data['menu_data']['protein'] == 33.0
        assert new_state.data['menu_data']['fats'] == 13.0
        assert new_state.data['menu_data']['carbs'] == 61.0
        
        # Проверить что caption обновился
        assert new_state.data['caption'] == 'ужин'
    
    def test_menu_data_updated_if_new_provided(
        self, 
        state_manager,
        sample_menu_data
    ):
        """Проверить что новый menu_data перезаписывает старый."""
        user_id = "test_user_456"
        
        # Создать состояние со старым menu_data
        old_menu = sample_menu_data.copy()
        old_menu['calories'] = 300.0
        
        existing_state = UserState(
            user_id=user_id,
            state='waiting_description',
            data={
                'photo_paths': ['/tmp/old.jpg'],
                'menu_data': old_menu
            }
        )
        state_manager.set_state(user_id, existing_state)
        
        # Обновить с НОВЫМ menu_data
        new_menu = sample_menu_data.copy()
        new_menu['calories'] = 500.0
        
        updated_state = create_photo_state(
            user_id=user_id,
            photo_paths=[Path('/tmp/new.jpg')],
            photo_file_ids=['new_file'],
            menu_data=new_menu,  # ← Передаём новый
            existing_state=existing_state
        )
        
        # Должен использоваться НОВЫЙ menu_data
        assert updated_state.data['menu_data']['calories'] == 500.0
    
    def test_update_menu_data_preserves_other_fields(
        self,
        state_manager,
        sample_menu_data
    ):
        """Проверить что обновление menu_data не трогает остальные поля."""
        user_id = "test_user_789"
        
        # Создать состояние с caption и photo_paths
        initial_state = UserState(
            user_id=user_id,
            state='waiting_description',
            data={
                'photo_paths': ['/tmp/photo1.jpg', '/tmp/photo2.jpg'],
                'photo_file_ids': ['file1', 'file2'],
                'caption': 'ужин',
                'menu_data': None
            }
        )
        state_manager.set_state(user_id, initial_state)
        
        # Обновить только menu_data
        updated_state = update_state_menu_data(user_id, sample_menu_data, state_manager)
        
        # menu_data должен появиться
        assert updated_state.data['menu_data'] is not None
        assert updated_state.data['menu_data']['calories'] == 500.0
        
        # Остальные поля должны сохраниться
        assert updated_state.data['caption'] == 'ужин'
        assert len(updated_state.data['photo_paths']) == 2
        assert updated_state.data['photo_file_ids'] == ['file1', 'file2']

    
    def test_preserve_and_merge_keeps_critical_keys(self):
        """Проверить что critical keys сохраняются при слиянии."""
        existing = {
            'menu_data': {'calories': 500},
            'caption': 'старая подпись',
            'photo_paths': ['/old/path']
        }
        
        new = {
            'caption': 'новая подпись',
            'photo_paths': ['/new/path']
        }
        
        merged = preserve_and_merge_state_data(
            existing, 
            new,
            preserve_keys=['menu_data']
        )
        
        # menu_data сохранён из existing
        assert 'menu_data' in merged
        assert merged['menu_data']['calories'] == 500
        
        # caption обновлён из new
        assert merged['caption'] == 'новая подпись'
        
        # photo_paths обновлён из new
        assert merged['photo_paths'] == ['/new/path']


class TestMenuDataValidation:
    """Тесты валидации MenuData через Pydantic."""
    
    def test_menu_data_requires_mandatory_fields(self):
        """Проверить что обязательные поля валидируются."""
        with pytest.raises(Exception):  # ValidationError from pydantic
            MenuData(
                dish_name="Тест",
                # calories отсутствует - должна быть ошибка!
                protein=10.0,
                fats=5.0,
                carbs=20.0
            )
    
    def test_menu_data_validates_positive_values(self):
        """Проверить что КБЖУ не могут быть отрицательными."""
        with pytest.raises(Exception):  # ValidationError
            MenuData(
                dish_name="Тест",
                calories=-100,  # Отрицательное значение!
                protein=10.0,
                fats=5.0,
                carbs=20.0
            )
    
    def test_menu_data_accepts_valid_data(self, sample_menu_data):
        """Проверить что валидные данные принимаются."""
        menu = MenuData(**sample_menu_data)
        
        assert menu.dish_name == 'Рыбные кебабы с гарниром из зелёного горошка'
        assert menu.calories == 500.0
        assert menu.protein == 33.0
        assert menu.source == 'chatgpt_vision'


class TestStateHelpers:
    """Тесты для helper функций."""
    
    def test_get_menu_data_returns_none_for_missing_state(
        self,
        state_manager
    ):
        """Проверить что get_menu_data возвращает None если нет состояния."""
        menu = get_menu_data_from_state("nonexistent_user")
        assert menu is None
    
    def test_get_menu_data_returns_typed_object(
        self,
        state_manager,
        sample_menu_data
    ):
        """Проверить что get_menu_data возвращает MenuData объект."""
        user_id = "test"
        state = UserState(
            user_id=user_id,
            state='waiting_description',
            data={'menu_data': sample_menu_data}
        )
        state_manager.set_state(user_id, state)
        
        menu = get_menu_data_from_state(user_id, state_manager)
        
        assert isinstance(menu, MenuData)
        assert menu.calories == 500.0



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
