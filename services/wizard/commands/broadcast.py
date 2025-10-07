"""Broadcast command flow."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Optional

from telegram import Message, Update
from telegram.ext import ContextTypes

from .base import CommandDependencies, WizardCommand
from .utils import (
    create_task,
    fetch_userbot_groups,
    get_group_stats,
    parse_custom_target_ids,
)


MODE_MANUAL = "📝 Manual Message"
MODE_FORWARD = "🔁 Forward Message"

SCOPE_ALL_GROUPS = "🌐 All Groups"
SCOPE_ALL_CHANNELS = "📡 All Channels"
SCOPE_CUSTOM = "🎯 Specific Targets"

SCHEDULE_NOW = "▶️ Send Now"
SCHEDULE_DELAY = "⏳ Delay"
SCHEDULE_INTERVAL = "🔁 Interval"

UPLOAD_DIR = Path("data/uploads")


class BroadcastCommand(WizardCommand):
    def __init__(self, deps: CommandDependencies) -> None:
        super().__init__(
            slug="broadcast",
            label="📢 Broadcast",
            description="Kirim pesan ke banyak grup sekaligus, dengan opsi jadwal.",
            deps=deps,
        )

    async def entry(self, update: Update, context: ContextTypes.DEFAULT_TYPE, userbot_id: int) -> str | None:
        state = self.get_state(context)
        state.clear()
        state.update({
            "step": "choose_mode",
            "userbot_id": userbot_id,
        })

        options = [[MODE_MANUAL, MODE_FORWARD]]
        reply_markup = self.make_keyboard(options)
        message = (
            "📢 *Broadcast*\n"
            "Pilih mode pengiriman pesan terlebih dahulu.\n"
            "• `📝 Manual Message` — ketik pesan baru (mendukung teks dan media dengan caption).\n"
            "• `🔁 Forward Message` — forward pesan yang sudah ada untuk disebarkan."
        )
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")
        self.log_out(update.effective_user.id, message)
        return None

    async def handle_response(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        userbot_id: int,
    ) -> tuple[bool, str | None]:
        message = update.message
        if not message:
            return False, None

        text = (message.text or "").strip()
        if self.is_back(text):
            self.reset(context)
            return True, "Kembali ke menu Kelola Userbot."

        state = self.get_state(context)
        step = state.get("step")

        if step == "choose_mode":
            return await self._handle_mode_choice(message, context)
        if step == "collect_manual_message":
            return await self._handle_manual_message(message, context)
        if step == "collect_forward_source":
            return await self._handle_forward_source(message, context)
        if step == "choose_schedule":
            return await self._handle_schedule_choice(message, context)
        if step == "input_schedule_minutes":
            return await self._handle_schedule_minutes(message, context)
        if step == "choose_scope":
            return await self._handle_scope_choice(message, context, userbot_id)
        if step == "custom_targets":
            return await self._handle_custom_targets(message, context)

        self.logger.warning("State broadcast tidak dikenal: %s", step)
        self.reset(context)
        return True, "Terjadi kesalahan, silakan ulangi broadcast."

    async def _handle_mode_choice(self, message: Message, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str | None]:
        choice = (message.text or "").strip()
        state = self.get_state(context)

        if choice == MODE_MANUAL:
            state["mode"] = "manual"
            state["step"] = "collect_manual_message"
            instructions = (
                "Kirim pesan broadcast yang ingin disebarkan.\n"
                "• Bisa berupa teks biasa.\n"
                "• Bisa juga berupa gambar/dokumen dengan caption (bot akan mengunduh otomatis)."
            )
            reply_markup = self.make_keyboard()
            await message.reply_text(instructions, reply_markup=reply_markup)
            self.log_out(message.from_user.id, instructions)
            return False, None

        if choice == MODE_FORWARD:
            state["mode"] = "forward"
            state["step"] = "collect_forward_source"
            instructions = (
                "Forward pesan yang ingin dikirim ke broadcast ke chat ini.\n"
                "Pastikan pesan berasal dari chat/grup yang juga diikuti oleh userbot."
            )
            reply_markup = self.make_keyboard()
            await message.reply_text(instructions, reply_markup=reply_markup)
            self.log_out(message.from_user.id, instructions)
            return False, None

        return False, "❌ Pilih mode broadcast melalui tombol yang tersedia."

    async def _handle_manual_message(self, message: Message, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str | None]:
        content = await self._extract_manual_content(message, context)
        if content is None:
            error = "❌ Jenis pesan belum didukung. Kirim teks atau lampirkan gambar/dokumen dengan caption."
            await message.reply_text(error, reply_markup=self.make_keyboard())
            self.log_out(message.from_user.id, error)
            return False, None

        state = self.get_state(context)
        state["content"] = content
        state["step"] = "choose_schedule"
        await self._send_schedule_prompt(message)
        return False, None

    async def _handle_forward_source(self, message: Message, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str | None]:
        forward_chat = message.forward_from_chat
        forward_msg_id = message.forward_from_message_id
        if not forward_chat or not forward_msg_id:
            error = "❌ Pesan tidak memiliki informasi sumber. Forward pesan langsung dari chat aslinya."
            await message.reply_text(error, reply_markup=self.make_keyboard())
            self.log_out(message.from_user.id, error)
            return False, None

        content = {
            "type": "forward",
            "from_chat_id": forward_chat.id,
            "from_chat_type": forward_chat.type,
            "message_id": forward_msg_id,
        }
        state = self.get_state(context)
        state["content"] = content
        state["step"] = "choose_schedule"
        await self._send_schedule_prompt(message)
        return False, None

    async def _handle_schedule_choice(self, message: Message, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str | None]:
        choice = (message.text or "").strip()
        state = self.get_state(context)

        if choice == SCHEDULE_NOW:
            state["schedule"] = {"mode": "now", "minutes": 0}
            state["step"] = "choose_scope"
            await self._send_scope_prompt(message, state["userbot_id"])
            return False, None

        if choice in {SCHEDULE_DELAY, SCHEDULE_INTERVAL}:
            state["pending_schedule_mode"] = "delay" if choice == SCHEDULE_DELAY else "interval"
            state["step"] = "input_schedule_minutes"
            warning = (
                "⏳ Masukkan jumlah menit (min 1) untuk jeda.\n"
                "⚠️ Gunakan jeda cukup panjang agar terhindar dari FloodWait."
            )
            await message.reply_text(warning, reply_markup=self.make_keyboard())
            self.log_out(message.from_user.id, warning)
            return False, None

        return False, "❌ Pilih salah satu mode waktu yang tersedia."

    async def _handle_schedule_minutes(self, message: Message, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str | None]:
        raw = (message.text or "").strip()
        if not raw.isdigit():
            return False, "❌ Masukkan angka menit yang valid (contoh: `5`)."
        minutes = int(raw)
        if minutes < 1:
            return False, "❌ Minimal 1 menit. Gunakan nilai lebih besar agar aman dari FloodWait."

        state = self.get_state(context)
        mode = state.pop("pending_schedule_mode", "delay")
        state["schedule"] = {"mode": mode, "minutes": minutes}
        state["step"] = "choose_scope"
        await self._send_scope_prompt(message, state["userbot_id"])
        return False, None

    async def _handle_scope_choice(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE, userbot_id: int
    ) -> tuple[bool, str | None]:
        text = (message.text or "").strip()
        state = self.get_state(context)

        if text == SCOPE_ALL_GROUPS:
            targets = [int(row["telegram_group_id"]) for row in fetch_userbot_groups(userbot_id, "group")]
            if not targets:
                return False, "❌ Tidak ada grup tersinkron. Jalankan 📂 Sync Users Groups terlebih dahulu."
            state.update({"scope": "all_groups", "targets": targets})
            return await self._finalize(message, context)

        if text == SCOPE_ALL_CHANNELS:
            targets = [int(row["telegram_group_id"]) for row in fetch_userbot_groups(userbot_id, "channel")]
            if not targets:
                return False, "❌ Tidak ada channel tersinkron. Jalankan 📂 Sync Users Groups terlebih dahulu."
            state.update({"scope": "all_channels", "targets": targets})
            return await self._finalize(message, context)

        if text == SCOPE_CUSTOM:
            state["scope"] = "custom"
            state["step"] = "custom_targets"
            instructions = (
                "🎯 Masukkan ID chat target (tanpa `-100`).\n"
                "• Pisahkan dengan koma jika lebih dari satu.\n"
                "• Contoh: `1234567890,987654321`."
            )
            await message.reply_text(instructions, reply_markup=self.make_keyboard(), parse_mode="Markdown")
            self.log_out(message.from_user.id, instructions)
            return False, None

        return False, "❌ Pilih salah satu opsi target yang tersedia."

    async def _handle_custom_targets(self, message: Message, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str | None]:
        try:
            targets = parse_custom_target_ids(message.text or "")
        except ValueError as exc:
            return False, f"❌ {exc}"

        state = self.get_state(context)
        state["targets"] = targets
        state["scope"] = "custom"
        return await self._finalize(message, context)

    async def _finalize(self, message: Message, context: ContextTypes.DEFAULT_TYPE) -> tuple[bool, str | None]:
        state = self.get_state(context)
        targets = state.get("targets", [])
        if not targets:
            return False, "❌ Tidak ada target yang valid untuk broadcast."

        details = {
            "mode": state.get("mode", "manual"),
            "content": state.get("content"),
            "schedule": state.get("schedule", {"mode": "now", "minutes": 0}),
            "targets": targets,
            "scope": state.get("scope", "custom"),
        }

        process_id, task_id = create_task(state["userbot_id"], "broadcast", details)
        scope_desc = self._describe_scope(details["scope"], len(targets))
        schedule_desc = self._describe_schedule(details["schedule"])
        summary = (
            "✅ Broadcast dijadwalkan!\n"
            f"• Task ID: {task_id}\n"
            f"• Process ID: `{process_id}`\n"
            f"• Mode pesan: {details['mode']}\n"
            f"• Target: {scope_desc}\n"
            f"• Jadwal: {schedule_desc}"
        )

        self.reset(context)
        return True, summary

    async def _extract_manual_content(self, message: Message, context: ContextTypes.DEFAULT_TYPE) -> Optional[dict]:
        if message.text:
            return {"type": "text", "text": message.text}

        if message.caption or message.photo or message.document:
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

            if message.photo:
                photo = message.photo[-1]
                file_path = await self._download_file(context, photo.file_id, ".jpg")
                return {
                    "type": "photo",
                    "path": file_path,
                    "caption": message.caption or "",
                }

            if message.document:
                extension = Path(message.document.file_name or "attachment").suffix or ".bin"
                file_path = await self._download_file(context, message.document.file_id, extension)
                return {
                    "type": "document",
                    "path": file_path,
                    "caption": message.caption or "",
                    "filename": message.document.file_name,
                }

        return None

    async def _download_file(self, context: ContextTypes.DEFAULT_TYPE, file_id: str, suffix: str) -> str:
        bot = context.bot
        file = await bot.get_file(file_id)
        filename = f"broadcast_{uuid.uuid4().hex}{suffix}"
        target_path = UPLOAD_DIR / filename
        await file.download_to_drive(str(target_path))
        return str(target_path)

    async def _send_schedule_prompt(self, message: Message) -> None:
        options = [[SCHEDULE_NOW, SCHEDULE_DELAY, SCHEDULE_INTERVAL]]
        prompt = (
            "Pilih kapan broadcast dijalankan.\n"
            "• `▶️ Send Now` — kirim segera.\n"
            "• `⏳ Delay` — kirim sekali setelah X menit.\n"
            "• `🔁 Interval` — kirim berulang tiap X menit."
        )
        reply_markup = self.make_keyboard(options)
        await message.reply_text(prompt, reply_markup=reply_markup, parse_mode="Markdown")
        self.log_out(message.from_user.id, prompt)

    async def _send_scope_prompt(self, message: Message, userbot_id: int) -> None:
        groups_count, channels_count = get_group_stats(userbot_id)
        options = [[SCOPE_ALL_GROUPS, SCOPE_ALL_CHANNELS], [SCOPE_CUSTOM]]
        prompt = (
            "Pilih target broadcast.\n"
            f"• Grup tersimpan: {groups_count}\n"
            f"• Kanal tersimpan: {channels_count}\n"
            "Jika memilih target tertentu, masukkan ID chat (tanpa `-100`)."
        )
        reply_markup = self.make_keyboard(options)
        await message.reply_text(prompt, reply_markup=reply_markup, parse_mode="Markdown")
        self.log_out(message.from_user.id, prompt)

    def _describe_scope(self, scope: str, total_targets: int) -> str:
        if scope == "all_groups":
            return f"Semua grup ({total_targets})"
        if scope == "all_channels":
            return f"Semua channel ({total_targets})"
        return f"Custom ({total_targets} chat)"

    def _describe_schedule(self, schedule: dict) -> str:
        mode = schedule.get("mode")
        minutes = schedule.get("minutes", 0)
        if mode == "now":
            return "Langsung"
        if mode == "delay":
            return f"Delay {minutes} menit"
        if mode == "interval":
            return f"Interval {minutes} menit"
        return "Tidak dikenal"


def build_command(deps: CommandDependencies) -> BroadcastCommand:
    return BroadcastCommand(deps)
