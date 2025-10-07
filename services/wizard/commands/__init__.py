"""Wizard command registry."""
from __future__ import annotations

from typing import Dict, Iterable, List

from .base import CommandDependencies, WizardCommand
from . import autoreply, watcher, broadcast, info, stop_job, help_command


def build_command_registry(deps: CommandDependencies) -> Dict[str, WizardCommand]:
    commands: List[WizardCommand] = [
        autoreply.build_command(deps),
        watcher.build_command(deps),
        broadcast.build_command(deps),
        info.build_command(deps),
        stop_job.build_command(deps),
        help_command.build_command(deps),
    ]
    return {cmd.label: cmd for cmd in commands}


def list_command_labels(commands: Iterable[WizardCommand]) -> List[str]:
    return [cmd.label for cmd in commands]
