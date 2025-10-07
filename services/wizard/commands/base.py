"""Utilities and base classes for wizard commands."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes


@dataclass(slots=True)
class CommandDependencies:
    """Dependencies that every wizard command requires."""
    logger: Any
    log_outgoing: Callable[[int, str], None]
    log_incoming: Callable[[Update, str], None]
    back_button: str


class WizardCommand(ABC):
    """Base class for wizard-side commands triggered from the manage menu."""

    def __init__(self, slug: str, label: str, description: str, deps: CommandDependencies) -> None:
        self.slug = slug
        self.label = label
        self.description = description
        self._deps = deps
        self._state_key = f"command_state::{slug}"
        self._back_button = deps.back_button

    @abstractmethod
    async def entry(self, update: Update, context: ContextTypes.DEFAULT_TYPE, userbot_id: int) -> str | None:
        """Handle the first interaction right after the command is picked.

        Should return a message that will be sent back to the admin. When the command
        performs an action instantly and does not require follow-up input it can
        return a confirmation message and conclude by calling :meth:`reset`.
        """

    @abstractmethod
    async def handle_response(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        userbot_id: int,
    ) -> tuple[bool, str | None]:
        """Process a follow-up message from the admin.

        Returns a tuple ``(is_completed, response_message)``. When ``is_completed``
        is ``True`` the conversation will return to the manage menu.
        """

    async def cancel(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Cleanup state when the command flow is interrupted."""
        self.reset(context)

    # ------------------------------------------------------------------
    # Helpers
    def get_state(self, context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
        return context.user_data.setdefault(self._state_key, {})

    def reset(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        context.user_data.pop(self._state_key, None)

    # Logging shorthands ------------------------------------------------
    def log_out(self, user_id: int, message: str) -> None:
        self._deps.log_outgoing(user_id, message)

    def log_in(self, update: Update, message: str) -> None:
        self._deps.log_incoming(update, message)

    @property
    def logger(self):
        return self._deps.logger

    # Keyboard helpers ---------------------------------------------------
    def make_keyboard(self, rows: list[list[str]] | None = None) -> ReplyKeyboardMarkup:
        rows = rows or []
        keyboard: list[list[str]] = [row[:] for row in rows if row]
        if not any(self._back_button in row for row in keyboard):
            keyboard.append([self._back_button])
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    @property
    def back_button(self) -> str:
        return self._back_button

    def is_back(self, text: str | None) -> bool:
        return (text or "").strip().lower() == self._back_button.strip().lower()
