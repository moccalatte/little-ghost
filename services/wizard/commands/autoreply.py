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

KEYWORD_MATCH_RELAXED = "🧩 Boleh potongan kata"
KEYWORD_MATCH_SPECIFIC = "🔍 Spesifik (kata harus utuh)"

KEYWORD_LOGIC_ANY = "🙂 Minimal satu kata cocok"
KEYWORD_LOGIC_ALL = "✅ Semua kata harus muncul"

EXCLUSION_MATCH_RELAXED = "🧩 Kata larangan boleh potongan"
EXCLUSION_MATCH_SPECIFIC = "🔍 Kata larangan harus utuh"

EXCLUSION_LOGIC_ANY = "🚫 Stop jika salah satu muncul"
EXCLUSION_LOGIC_ALL = "🧱 Stop jika semua muncul"


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
        if step == "choose_keyword_match_type":
            return await self._handle_keyword_match_type(message, context)
        if step == "choose_keyword_logic":
            return await self._handle_keyword_logic(message, context)
        if step == "ask_exclusion":
            return await self._handle_exclusion_choice(message, context)
        if step == "collect_exclusion":
            return await self._handle_exclusion_input(message, context)
        if step == "choose_exclusion_match_type":
            return await self._handle_exclusion_match_type(message, context)
        if step == "choose_exclusion_logic":
            return await self._handle_exclusion_logic(message, context)
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
        state["pending_exclusions"] = exclusions_from_text or []
        state["step"] = "choose_keyword_match_type"
        await self._send_keyword_match_type_prompt(message)
        return False, None

    async def _handle_keyword_match_type(
        self, message: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        text = (message.text or "").strip()
        state = self.get_state(context)

        if text == KEYWORD_MATCH_RELAXED:
            state["keyword_match_type"] = "contains"
        elif text == KEYWORD_MATCH_SPECIFIC:
            state["keyword_match_type"] = "specific"
        else:
            reminder = "❌ Jawab pakai tombol yang tersedia ya supaya gampang."
            await message.reply_text(reminder, reply_markup=self.make_keyboard([[KEYWORD_MATCH_SPECIFIC], [KEYWORD_MATCH_RELAXED]]))
            self.log_out(message.from_user.id, reminder)
            return False, None

        state["step"] = "choose_keyword_logic"
        await self._send_keyword_logic_prompt(message)
        return False, None

    async def _handle_keyword_logic(
        self, message: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        text = (message.text or "").strip()
        state = self.get_state(context)

        if text == KEYWORD_LOGIC_ANY:
            state["keyword_logic"] = "any"
        elif text == KEYWORD_LOGIC_ALL:
            state["keyword_logic"] = "all"
        else:
            reminder = "❌ Tinggal pilih salah satu tombol di bawah ya."
            await message.reply_text(reminder, reply_markup=self.make_keyboard([[KEYWORD_LOGIC_ANY], [KEYWORD_LOGIC_ALL]]))
            self.log_out(message.from_user.id, reminder)
            return False, None

        pending_exclusions = state.pop("pending_exclusions", [])
        if pending_exclusions:
            state["exclusions"] = pending_exclusions
            state["step"] = "choose_exclusion_match_type"
            await self._send_exclusion_match_type_prompt(message)
            return False, None

        state.setdefault("exclusions", [])
        state["step"] = "ask_exclusion"
        options = [[OPTION_ADD_EXCLUSION, OPTION_SKIP_EXCLUSION]]
        reply_markup = self.make_keyboard(options)
        prompt = (
            "Mau tambahkan kata yang harus diabaikan?\n"
            "Pilih `🚫 Tambah pengecualian` kalau perlu, atau `➡️ Lanjut tanpa pengecualian`."
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
            state["exclusion_match_type"] = "contains"
            state["exclusion_logic"] = "any"
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
        state["step"] = "choose_exclusion_match_type"
        await self._send_exclusion_match_type_prompt(message)
        return False, None

    async def _handle_exclusion_match_type(
        self, message: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        text = (message.text or "").strip()
        state = self.get_state(context)

        if text == EXCLUSION_MATCH_RELAXED:
            state["exclusion_match_type"] = "contains"
        elif text == EXCLUSION_MATCH_SPECIFIC:
            state["exclusion_match_type"] = "specific"
        else:
            reminder = "❌ Yuk pakai tombol pilihan supaya wizard paham."
            await message.reply_text(reminder, reply_markup=self.make_keyboard([[EXCLUSION_MATCH_SPECIFIC], [EXCLUSION_MATCH_RELAXED]]))
            self.log_out(message.from_user.id, reminder)
            return False, None

        state["step"] = "choose_exclusion_logic"
        await self._send_exclusion_logic_prompt(message)
        return False, None

    async def _handle_exclusion_logic(
        self, message: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        text = (message.text or "").strip()
        state = self.get_state(context)

        if text == EXCLUSION_LOGIC_ANY:
            state["exclusion_logic"] = "any"
        elif text == EXCLUSION_LOGIC_ALL:
            state["exclusion_logic"] = "all"
        else:
            reminder = "❌ Pilih salah satu tombol supaya wizard tahu kapan harus stop."
            await message.reply_text(reminder, reply_markup=self.make_keyboard([[EXCLUSION_LOGIC_ANY], [EXCLUSION_LOGIC_ALL]]))
            self.log_out(message.from_user.id, reminder)
            return False, None

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
        keyword_match_type = state.get("keyword_match_type", "contains")
        keyword_logic = state.get("keyword_logic", "any")
        exclusion_match_type = state.get("exclusion_match_type", "contains")
        exclusion_logic = state.get("exclusion_logic", "any")

        details = {
            "targets": targets,
            "keywords": keywords,
            "exclusions": exclusions,
            "reply_text": reply_text,
            "scope": scope,
            "keyword_match_type": keyword_match_type,
            "keyword_logic": keyword_logic,
            "exclusion_match_type": exclusion_match_type,
            "exclusion_logic": exclusion_logic,
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
        summary_lines.append(
            "• Cara cek kata: "
            + ("spesifik" if keyword_match_type == "specific" else "boleh potongan")
            + (" & semua harus ada" if keyword_logic == "all" else " & cukup salah satu")
        )
        if exclusions:
            summary_lines.append(
                "• Abaikan kata: "
                + ", ".join(exclusions)
                + " ("
                + ("spesifik" if exclusion_match_type == "specific" else "boleh potongan")
                + (" & semua" if exclusion_logic == "all" else " & salah satu")
                + ")"
            )
        summary_lines.append("Userbot akan segera memprosesnya.")
        summary = "\n".join(summary_lines)
        return True, summary

    # ------------------------------------------------------------------
    async def _send_keywords_prompt(self, message: Message) -> None:
        prompt = (
            "Langkah berikut — tuliskan kata yang mau dipantau.\n"
            "• Pisahkan dengan koma jika lebih dari satu (contoh: `need,nit`).\n"
            "• Boleh menambahkan `tanpa ...` di belakang untuk langsung bikin larangan (contoh: `need,nit tanpa spam`)."
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

    async def _send_keyword_match_type_prompt(self, message: Message) -> None:
        options = [[KEYWORD_MATCH_SPECIFIC], [KEYWORD_MATCH_RELAXED]]
        reply_markup = self.make_keyboard(options)
        prompt = (
            "Cara cek katanya mau yang mana?\n"
            "• `Spesifik` artinya kata harus berdiri sendiri (kata `nit` tidak akan kena `menit`).\n"
            "• `Boleh potongan kata` cocok kalau cukup ada bagian katanya saja."
        )
        await message.reply_text(prompt, reply_markup=reply_markup)
        self.log_out(message.from_user.id, prompt)

    async def _send_keyword_logic_prompt(self, message: Message) -> None:
        options = [[KEYWORD_LOGIC_ANY], [KEYWORD_LOGIC_ALL]]
        reply_markup = self.make_keyboard(options)
        prompt = (
            "Kalau kamu menulis lebih dari satu kata, apakah semua harus muncul?\n"
            "• `Minimal satu kata cocok` = mode ATAU (cukup salah satunya).\n"
            "• `Semua kata harus muncul` = mode DAN."
        )
        await message.reply_text(prompt, reply_markup=reply_markup)
        self.log_out(message.from_user.id, prompt)

    async def _send_exclusion_match_type_prompt(self, message: Message) -> None:
        options = [[EXCLUSION_MATCH_SPECIFIC], [EXCLUSION_MATCH_RELAXED]]
        reply_markup = self.make_keyboard(options)
        prompt = (
            "Sekarang pilih cara membaca kata larangan.\n"
            "• `Kata larangan harus utuh` supaya `nit` tidak memblokir `menit`.\n"
            "• `Kata larangan boleh potongan` kalau cukup ada potongan katanya saja."
        )
        await message.reply_text(prompt, reply_markup=reply_markup)
        self.log_out(message.from_user.id, prompt)

    async def _send_exclusion_logic_prompt(self, message: Message) -> None:
        options = [[EXCLUSION_LOGIC_ANY], [EXCLUSION_LOGIC_ALL]]
        reply_markup = self.make_keyboard(options)
        prompt = (
            "Terakhir, pilih kapan balasan harus dibatalkan.\n"
            "• `Stop jika salah satu muncul` = cukup satu kata larangan untuk batal.\n"
            "• `Stop jika semua muncul` = baru batal kalau semua kata larangan ada."
        )
        await message.reply_text(prompt, reply_markup=reply_markup)
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
