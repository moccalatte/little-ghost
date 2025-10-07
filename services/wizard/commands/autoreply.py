"""Auto-reply wizard command flow."""
from __future__ import annotations

import re
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


SCOPE_ALL_GROUPS = "🌐 All Groups"
SCOPE_ALL_CHANNELS = "📡 All Channels"
SCOPE_CUSTOM = "🎯 Specific Targets"

OPTION_ADD_EXCLUSION = "🚫 Tambah pengecualian"
OPTION_SKIP_EXCLUSION = "➡️ Lanjut tanpa pengecualian"


class AutoReplyCommand(WizardCommand):
    def __init__(self, deps: CommandDependencies) -> None:
        super().__init__(
            slug="auto_reply",
            label="🤖 Auto Reply",
            description="Buat aturan balasan otomatis berdasarkan kata kunci untuk grup/kanal tertentu.",
            deps=deps,
        )

    async def entry(self, update: Update, context: ContextTypes.DEFAULT_TYPE, userbot_id: int) -> str | None:
        state = self.get_state(context)
        state.clear()
        state.update({
            "step": "choose_scope",
            "userbot_id": userbot_id,
        })

        groups_count, channels_count = get_group_stats(userbot_id)
        scope_rows = [[SCOPE_ALL_GROUPS, SCOPE_ALL_CHANNELS], [SCOPE_CUSTOM]]
        reply_markup = self.make_keyboard(scope_rows)
        message = (
            "🤖 *Auto Reply*\n"
            "Pilih target chat terlebih dahulu.\n"
            f"• Grup tersimpan: {groups_count}\n"
            f"• Kanal tersimpan: {channels_count}\n\n"
            "Gunakan opsi di bawah. Untuk target tertentu, Anda akan diminta memasukkan ID chat (tanpa `-100`).\n"
            "👉 Cara cepat melihat ID: buka Info Grup ➜ Salin \"ID\" atau gunakan bot @userinfobot."
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

        if step == "choose_scope":
            return await self._handle_scope_choice(message, context, userbot_id)
        if step == "custom_targets":
            return await self._handle_custom_targets(message, context)
        if step == "collect_keywords":
            return await self._handle_keywords(message, context)
        if step == "ask_exclusion":
            return await self._handle_exclusion_choice(message, context)
        if step == "collect_exclusion":
            return await self._handle_exclusion_input(message, context)
        if step == "collect_reply":
            return await self._handle_reply(message, context, userbot_id)

        self.logger.warning("State auto_reply tidak dikenal: %s", step)
        self.reset(context)
        return True, "Terjadi kesalahan kecil, silakan mulai lagi."

    async def _handle_scope_choice(
        self, message: Update, context: ContextTypes.DEFAULT_TYPE, userbot_id: int
    ) -> tuple[bool, str | None]:
        text = (message.text or "").strip()
        state = self.get_state(context)

        if text == SCOPE_ALL_GROUPS:
            targets = [int(row["telegram_group_id"]) for row in fetch_userbot_groups(userbot_id, "group")]
            if not targets:
                return False, "❌ Tidak ada grup yang tersinkron. Jalankan 📂 Sync Users Groups terlebih dahulu."
            state.update({"scope": "all_groups", "targets": targets})
            state["step"] = "collect_keywords"
            return False, self._keywords_prompt()

        if text == SCOPE_ALL_CHANNELS:
            targets = [int(row["telegram_group_id"]) for row in fetch_userbot_groups(userbot_id, "channel")]
            if not targets:
                return False, "❌ Tidak ada channel yang tersinkron. Jalankan 📂 Sync Users Groups terlebih dahulu."
            state.update({"scope": "all_channels", "targets": targets})
            state["step"] = "collect_keywords"
            return False, self._keywords_prompt()

        if text == SCOPE_CUSTOM:
            state["scope"] = "custom"
            state["step"] = "custom_targets"
            instructions = (
                "🎯 Masukkan ID chat target (tanpa `-100`).\n"
                "• Pisahkan dengan koma bila lebih dari satu.\n"
                "• Contoh: `1234567890,987654321`."
            )
            reply_markup = self.make_keyboard()
            await message.reply_text(instructions, reply_markup=reply_markup, parse_mode="Markdown")
            self.log_out(message.from_user.id, instructions)
            return False, None

        return False, "❌ Pilih salah satu opsi yang tersedia pada keyboard."

    async def _handle_custom_targets(
        self, message: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        try:
            targets = parse_custom_target_ids(message.text or "")
        except ValueError as exc:
            return False, f"❌ {exc}"

        state = self.get_state(context)
        state["targets"] = targets
        state["step"] = "collect_keywords"
        await self._send_keywords_prompt(message)
        return False, None

    async def _handle_keywords(
        self, message: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        includes, exclusions_from_text = self._parse_keyword_input(message.text or "")
        if not includes:
            return False, "❌ Minimal harus ada satu kata kunci. Contoh: `need,nit`."

        state = self.get_state(context)
        state["keywords"] = includes

        if exclusions_from_text:
            state["exclusions"] = exclusions_from_text
            state["step"] = "collect_reply"
            await self._send_reply_prompt(message)
            return False, None

        state["step"] = "ask_exclusion"
        options = [[OPTION_ADD_EXCLUSION, OPTION_SKIP_EXCLUSION]]
        reply_markup = self.make_keyboard(options)
        prompt = (
            "Tambahkan kata yang harus diabaikan?\n"
            "Pilih `🚫 Tambah pengecualian` atau `➡️ Lanjut tanpa pengecualian`."
        )
        await message.reply_text(prompt, reply_markup=reply_markup)
        self.log_out(message.from_user.id, prompt)
        return False, None

    async def _handle_exclusion_choice(
        self, message: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        text = (message.text or "").strip()
        state = self.get_state(context)

        if text == OPTION_SKIP_EXCLUSION:
            state["exclusions"] = []
            state["step"] = "collect_reply"
            await self._send_reply_prompt(message)
            return False, None

        if text == OPTION_ADD_EXCLUSION:
            state["step"] = "collect_exclusion"
            instructions = (
                "Masukkan kata yang harus diabaikan, pisahkan dengan koma.\n"
                "Contoh: `nut,spam`."
            )
            reply_markup = self.make_keyboard()
            await message.reply_text(instructions, reply_markup=reply_markup)
            self.log_out(message.from_user.id, instructions)
            return False, None

        return False, "❌ Pilih opsi yang tersedia."

    async def _handle_exclusion_input(
        self, message: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        exclusions = [chunk.strip() for chunk in (message.text or "").split(",") if chunk.strip()]
        if not exclusions:
            return False, "❌ Masukkan minimal satu kata pengecualian atau pilih skip."

        state = self.get_state(context)
        state["exclusions"] = exclusions
        state["step"] = "collect_reply"
        await self._send_reply_prompt(message)
        return False, None

    async def _handle_reply(
        self,
        message: Update,
        context: ContextTypes.DEFAULT_TYPE,
        userbot_id: int,
    ) -> tuple[bool, str | None]:
        reply_text = (message.text or "").strip()
        if not reply_text:
            return False, "❌ Pesan balasan tidak boleh kosong."

        state = self.get_state(context)
        targets = state.get("targets", [])
        keywords = state.get("keywords", [])
        exclusions = state.get("exclusions", [])
        scope = state.get("scope", "custom")

        details = {
            "targets": targets,
            "keywords": keywords,
            "exclusions": exclusions,
            "reply_text": reply_text,
            "scope": scope,
        }

        process_id, task_id = create_task(userbot_id, "auto_reply", details)
        self.reset(context)

        scope_desc = self._describe_scope(scope, len(targets))
        summary_lines = [
            "✅ Auto reply siap dijalankan!",
            f"• Task ID: {task_id}",
            f"• Process ID: `{process_id}`",
            f"• Scope: {scope_desc}",
            f"• Kata kunci: {', '.join(keywords)}",
        ]
        if exclusions:
            summary_lines.append(f"• Abaikan kata: {', '.join(exclusions)}")
        summary_lines.append("Userbot akan segera memprosesnya.")
        summary = "\n".join(summary_lines)
        return True, summary

    # ------------------------------------------------------------------
    async def _send_keywords_prompt(self, message: Message) -> None:
        prompt = (
            "Langkah berikut — tuliskan kata kunci pemicu.\n"
            "• Pisahkan dengan koma jika lebih dari satu (contoh: `need,nit`).\n"
            "• Anda juga bisa menulis `need tanpa nut` untuk langsung menambahkan pengecualian."
        )
        reply_markup = self.make_keyboard()
        await message.reply_text(prompt, reply_markup=reply_markup, parse_mode="Markdown")
        self.log_out(message.from_user.id, prompt)

    async def _send_reply_prompt(self, message: Message) -> None:
        prompt = (
            "Sekarang tulis pesan balasan yang akan dikirim userbot.\n"
            "Contoh: `Halo! Ada yang bisa saya bantu?`"
        )
        reply_markup = self.make_keyboard()
        await message.reply_text(prompt, reply_markup=reply_markup, parse_mode="Markdown")
        self.log_out(message.from_user.id, prompt)

    def _parse_keyword_input(self, raw: str) -> tuple[List[str], Optional[List[str]]]:
        if not raw:
            return [], None
        parts = re.split(r"\btanpa\b", raw, maxsplit=1, flags=re.IGNORECASE)
        include_text = parts[0]
        exclusion_text = parts[1] if len(parts) > 1 else None
        includes = [chunk.strip() for chunk in include_text.replace(";", ",").split(",") if chunk.strip()]
        exclusions = None
        if exclusion_text:
            exclusions = [chunk.strip() for chunk in exclusion_text.replace(";", ",").split(",") if chunk.strip()]
        return includes, exclusions

    def _describe_scope(self, scope: str, total_targets: int) -> str:
        if scope == "all_groups":
            return f"Semua grup ({total_targets})"
        if scope == "all_channels":
            return f"Semua channel ({total_targets})"
        return f"Custom ({total_targets} chat)"


def build_command(deps: CommandDependencies) -> AutoReplyCommand:
    return AutoReplyCommand(deps)
