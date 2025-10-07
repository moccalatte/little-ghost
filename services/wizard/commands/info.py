"""Command to display task status summary."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from .base import CommandDependencies, WizardCommand
from .utils import fetch_userbot_tasks, safe_json_loads


class InfoCommand(WizardCommand):
    def __init__(self, deps: CommandDependencies) -> None:
        super().__init__(
            slug="info",
            label="📊 Job Status",
            description="Lihat daftar tugas userbot yang sedang atau sudah berjalan.",
            deps=deps,
        )

    async def entry(self, update: Update, context: ContextTypes.DEFAULT_TYPE, userbot_id: int) -> str | None:
        tasks = fetch_userbot_tasks(userbot_id)
        if not tasks:
            self.reset(context)
            return "Belum ada tugas yang pernah dijalankan untuk userbot ini."

        lines = ["📊 *Status Tugas Userbot*", ""]
        for row in tasks[:15]:  # batasi 15 entri terakhir agar mudah dibaca
            details = safe_json_loads(row["details"])
            lines.append(
                "• "
                f"`{row['process_id']}` — {row['command']} ({row['status']})"
            )
            if details.get("label"):
                lines.append(f"  ↳ Nama: {details['label']}")
            if details.get("schedule"):
                lines.append(f"  ↳ Jadwal: {details['schedule']}")
        if len(tasks) > 15:
            lines.append("\nMenampilkan 15 tugas terbaru. Gunakan dashboard SQLite untuk arsip penuh.")

        self.reset(context)
        return "\n".join(lines)

    async def handle_response(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        userbot_id: int,
    ) -> tuple[bool, str | None]:
        self.reset(context)
        return True, None


def build_command(deps: CommandDependencies) -> InfoCommand:
    return InfoCommand(deps)
