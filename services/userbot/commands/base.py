"""Base classes for userbot command handlers."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from telethon import TelegramClient


@dataclass(slots=True)
class CommandContext:
    """Context data shared with command implementations."""

    userbot_id: int
    process_id: str
    task_id: int
    details: Dict[str, Any]
    client: TelegramClient
    job_logger: Any
    update_status: Callable[[str, Optional[str]], Awaitable[None]]
    refresh_task_details: Callable[[Dict[str, Any]], Awaitable[None]]

    @property
    def logger(self):
        return self.job_logger


class ActiveCommand(ABC):
    """Handle returned by long-running commands."""

    def __init__(self) -> None:
        self._stop_callbacks: list[Callable[[], Awaitable[None] | None]] = []
        self._tasks: list[asyncio.Task[Any]] = []

    def add_stop_callback(self, callback: Callable[[], Awaitable[None] | None]) -> None:
        self._stop_callbacks.append(callback)

    async def stop(self) -> None:
        callbacks = list(self._stop_callbacks)
        for callback in callbacks:
            result = callback()
            if asyncio.iscoroutine(result):
                await result

    def register_task(self, task: asyncio.Task[Any]) -> None:
        """Ensure background tasks are cancelled when stop() is invoked."""
        async def _cancel_task() -> None:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.add_stop_callback(_cancel_task)
        self._tasks.append(task)

    @property
    def tasks(self) -> list[asyncio.Task[Any]]:
        return self._tasks


class UserbotCommand(ABC):
    """Interface for userbot command handlers."""

    slug: str

    def __init__(self, slug: str) -> None:
        self.slug = slug

    @abstractmethod
    async def start(self, ctx: CommandContext) -> Optional[ActiveCommand]:
        """Start the command logic.

        Should return an :class:`ActiveCommand` when the command needs to keep
        running in the background (e.g. auto reply, watcher, interval broadcast).
        Returning ``None`` indicates the command has completed synchronously.
        """
        raise NotImplementedError

    async def stop(self, active: ActiveCommand, ctx: CommandContext) -> None:
        """Called when the wizard requests the job to stop."""
        await active.stop()
