"""Additional contextual help for manage menu."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from .base import CommandDependencies, WizardCommand


HELP_TEXT = (
    "🆘 *Userbot Command Guide*\n\n"
    "• *🤖 Auto Reply* — balas pesan otomatis ketika kata kunci tertentu muncul.\n"
    "• *👀 Watcher* — pantau kata kunci dan catat hasilnya ke log atau Google Sheets.\n"
    "• *📢 Broadcast* — kirim pengumuman ke banyak chat sekaligus, bisa dijadwalkan.\n"
    "• *📊 Job Status* — lihat daftar task terbaru dan detail konfigurasinya.\n"
    "• *⛔ Stop Jobs* — hentikan task yang masih berjalan atau terjadwal.\n"
    "• Fitur sinkronisasi grup tersedia di menu Admin ➜ `👷 Manage Userbot (WIP)`.\n"
    "Gunakan `🤖 Choose Userbot` untuk berganti userbot dan ketik /menu kapan saja untuk kembali ke menu utama."
)


class HelpCommand(WizardCommand):
    def __init__(self, deps: CommandDependencies) -> None:
        super().__init__(
            slug="manage_help",
            label="🆘 Help",
            description="Tampilkan panduan singkat untuk menu kelola userbot.",
            deps=deps,
        )

    async def entry(self, update: Update, context: ContextTypes.DEFAULT_TYPE, userbot_id: int) -> str | None:
        self.reset(context)
        return HELP_TEXT

    async def handle_response(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        userbot_id: int,
    ) -> tuple[bool, str | None]:
        self.reset(context)
        return True, None


def build_command(deps: CommandDependencies) -> HelpCommand:
    return HelpCommand(deps)
