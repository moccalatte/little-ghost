"""Command to stop active userbot jobs."""
from __future__ import annotations

from typing import List

from telegram import Update
from telegram.ext import ContextTypes

from .base import CommandDependencies, WizardCommand
from .utils import fetch_userbot_tasks, mark_tasks_stopped, parse_selection_indexes


STOPPABLE_STATUSES = {"pending", "running", "scheduled", "interval"}


class StopJobCommand(WizardCommand):
    def __init__(self, deps: CommandDependencies) -> None:
        super().__init__(
            slug="stop_job",
            label="⛔ Stop Jobs",
            description="Hentikan task userbot yang sedang berjalan.",
            deps=deps,
        )

    async def entry(self, update: Update, context: ContextTypes.DEFAULT_TYPE, userbot_id: int) -> str | None:
        message = update.message
        if message is None:
            return None
        tasks = [row for row in fetch_userbot_tasks(userbot_id) if row["status"] in STOPPABLE_STATUSES]
        state = self.get_state(context)
        state.clear()
        state["tasks"] = [dict(row) for row in tasks]

        if not tasks:
            self.reset(context)
            info = (
                "⛔ *Stop Jobs*\n"
                "Saat ini tidak ada task aktif. Gunakan menu 📊 Job Status untuk memeriksa task lain."
            )
            await message.reply_text(info, reply_markup=self.make_keyboard(), parse_mode="Markdown")
            self.log_out(message.from_user.id, info)
            return None

        lines = [
            "⛔ *Stop Jobs*",
            "Process ID bisa dilihat melalui menu 📊 Job Status.",
            "• Ketik angka (contoh `1` atau `1,3`) untuk memilih dari daftar di bawah.",
            "• Masukkan langsung Process ID (misal: `d5f3-1234`).",
            "• Ketik `all` untuk menghentikan semua task aktif.",
            "Ketik 'batal' kapan saja untuk kembali.",
            "",
        ]
        preview_limit = 10
        for idx, row in enumerate(tasks[:preview_limit], start=1):
            lines.append(f"{idx}. {row['command']} — `{row['process_id']}` ({row['status']})")
        if len(tasks) > preview_limit:
            lines.append(f"\nMenampilkan {preview_limit} task pertama. Lihat 📊 Job Status untuk daftar lengkap.")

        state["step"] = "await_selection"
        text = "\n".join(lines)
        await message.reply_text(text, reply_markup=self.make_keyboard(), parse_mode="Markdown")
        self.log_out(message.from_user.id, text)
        return None

    async def handle_response(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        userbot_id: int,
    ) -> tuple[bool, str | None]:
        message = update.message
        assert message is not None
        text = (message.text or "").strip()
        lower = text.lower()

        if lower in {"batal", "cancel", "/cancel"}:
            self.reset(context)
            return True, "Tidak ada task yang dihentikan."

        state = self.get_state(context)
        step = state.get("step")
        if step != "await_selection":
            self.reset(context)
            return True, "Terjadi kesalahan, silakan buka menu lagi."

        tasks: List[dict] = state.get("tasks", [])
        process_ids: List[str]

        try:
            if lower == "all":
                process_ids = [row["process_id"] for row in tasks]
            elif text.count("-") >= 1 and len(text) > 10:
                process_ids = [text]
            else:
                indexes = parse_selection_indexes(text.replace(" ", ""), len(tasks))
                process_ids = [tasks[idx - 1]["process_id"] for idx in indexes]
        except ValueError as exc:
            return False, f"❌ {exc}. Silakan coba lagi."

        mark_tasks_stopped(userbot_id, process_ids)
        self.reset(context)
        summary = (
            "✅ Task dihentikan.\n"
            "Process ID: " + ", ".join(f"`{pid}`" for pid in process_ids)
            + "\nPeriksa menu 📊 Job Status untuk memastikan status berubah menjadi stopped."
        )
        return True, summary


def build_command(deps: CommandDependencies) -> StopJobCommand:
    return StopJobCommand(deps)
