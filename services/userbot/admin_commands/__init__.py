"""Administrative command implementations for the userbot service."""
from __future__ import annotations

from typing import Dict

from services.userbot.commands.base import UserbotCommand
from . import automated_testing, sync_groups


def build_admin_commands(command_registry: Dict[str, UserbotCommand]) -> Dict[str, UserbotCommand]:
    return {
        'auto_test': automated_testing.build_command(command_registry),
        'sync_groups': sync_groups.build_command(),
    }
