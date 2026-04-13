"""
Authorization middleware for Telegram bot.

Checks if users are in the whitelist before allowing access to bot commands.
"""

from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
import sys
from pathlib import Path

# Add project root to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.users import is_user_allowed


class AuthMiddleware(BaseMiddleware):
    """
    Middleware to check if user is authorized to use the bot.

    Validates user against whitelist and passes user_id to all handlers.
    """

    async def __call__(
        self, handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], event: Message, data: Dict[str, Any]
    ) -> Any:
        """
        Process message and check authorization.

        Args:
            handler: Next handler in chain
            event: Incoming message
            data: Handler data dictionary

        Returns:
            Handler result or None if unauthorized
        """
        # Skip authorization for non-message updates
        if not isinstance(event, Message):
            return await handler(event, data)

        user_id = event.from_user.id
        username = event.from_user.username or "Unknown"
        first_name = event.from_user.first_name or "User"

        # Check if user is allowed
        if not is_user_allowed(user_id):
            await event.answer(
                f"❌ Unauthorized Access\n\n"
                f"Sorry {first_name}, you are not authorized to use this bot.\n"
                f"Contact the administrator for access.\n\n"
                f"Your Telegram ID: `{user_id}`",
                parse_mode="Markdown",
            )
            return

        # Pass user info to all handlers
        data["user_id"] = user_id
        data["username"] = username
        data["first_name"] = first_name

        # Continue to handler
        return await handler(event, data)
