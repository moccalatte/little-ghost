"""Userbot command registry."""
from __future__ import annotations

from typing import Dict

from .base import UserbotCommand
from . import autoreply, watcher, broadcast
from services.userbot.admin_commands import build_admin_commands


def build_command_registry() -> Dict[str, UserbotCommand]:
    registry: Dict[str, UserbotCommand] = {
        'auto_reply': autoreply.build_command(),
        'watcher': watcher.build_command(),
        'broadcast': broadcast.build_command(),
    }
    registry.update(build_admin_commands(registry))
    return registry
