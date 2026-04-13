#!/usr/bin/env python3
"""
Модуль для управления состоянием пользователей бота
"""

from typing import Dict, Optional
from dataclasses import dataclass, field


@dataclass
class UserState:
    """Состояние пользователя"""

    user_id: str
    state: str  # 'waiting_description', 'waiting_confirmation', и т.д.
    data: Dict = field(default_factory=dict)


class StateManager:
    """Менеджер состояний пользователей (in-memory)"""

    def __init__(self):
        self._states: Dict[str, UserState] = {}

    def get_state(self, user_id: str) -> Optional[UserState]:
        """Получить состояние пользователя"""
        return self._states.get(user_id)

    def set_state(self, user_id: str, user_state: UserState):
        """Установить состояние пользователя"""
        self._states[user_id] = user_state

    def clear_state(self, user_id: str):
        """Очистить состояние пользователя"""
        if user_id in self._states:
            del self._states[user_id]


# Глобальный экземпляр менеджера состояний
state_manager = StateManager()
