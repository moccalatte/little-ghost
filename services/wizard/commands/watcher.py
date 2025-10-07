"""Watcher command to monitor messages and log matches."""
from __future__ import annotations

import re
from typing import List, Optional

from telegram import Message, Update
from telegram.ext import ContextTypes

from .base import CommandDependencies, WizardCommand
from .utils import (
    create_task,
    fetch_userbot_groups,
    fetch_userbot_tasks,
    get_group_stats,
    parse_custom_target_ids,
    safe_json_loads,
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

DEST_LOCAL = "🗂 Local Log"
DEST_SHEETS = "📄 Google Sheets"

ACTION_CREATE = "➕ Buat Watcher"
ACTION_LOGS = "📜 Watcher Logs"


class WatcherCommand(WizardCommand):
    def __init__(self, deps: CommandDependencies) -> None:
        super().__init__(
            slug="watcher",
            label="👀 Watcher",
            description="Pantau pesan dengan kata kunci tertentu dan catat hasilnya.",
            deps=deps,
        )

    async def entry(self, update: Update, context: ContextTypes.DEFAULT_TYPE, userbot_id: int) -> str | None:
        state = self.get_state(context)
        state.clear()
        state.update({"step": "choose_action", "userbot_id": userbot_id})

        options = [[ACTION_CREATE], [ACTION_LOGS]]
        reply_markup = self.make_keyboard(options)
        message = (
            "👀 *Watcher*\n"
            "Pilih aksi berikut:\n"
            "• `➕ Buat Watcher` untuk membuat rule baru.\n"
            "• `📜 Watcher Logs` untuk melihat riwayat eksekusi terakhir."
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

        if step == "choose_action":
            return await self._handle_action_choice(message, context, userbot_id)
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
        if step == "choose_destination":
            return await self._handle_destination_choice(message, context)
        if step == "collect_sheet":
            return await self._handle_sheet_input(message, context)
        if step == "collect_label":
            return await self._handle_label(message, context, userbot_id)

        self.logger.warning("State watcher tidak dikenal: %s", step)
        self.reset(context)
        return True, "Terjadi kesalahan kecil, silakan ulangi perintah."

    async def _handle_action_choice(
        self,
        message: Message,
        context: ContextTypes.DEFAULT_TYPE,
        userbot_id: int,
    ) -> tuple[bool, str | None]:
        text = (message.text or "").strip()
        state = self.get_state(context)

        if text == ACTION_CREATE:
            state["step"] = "choose_scope"
            groups_count, channels_count = get_group_stats(userbot_id)
            scope_rows = [[SCOPE_ALL_GROUPS, SCOPE_ALL_CHANNELS], [SCOPE_CUSTOM]]
            reply_markup = self.make_keyboard(scope_rows)
            prompt = (
                "🎯 Pilih target chat terlebih dahulu.\n"
                f"• Grup tersimpan: {groups_count}\n"
                f"• Kanal tersinkron: {channels_count}\n\n"
                "Jika memilih target tertentu, masukkan ID chat (tanpa `-100`).\n"
                "👉 Gunakan Info Grup atau bot @userinfobot untuk melihat ID."
            )
            await message.reply_text(prompt, reply_markup=reply_markup, parse_mode="Markdown")
            self.log_out(message.from_user.id, prompt)
            return False, None

        if text == ACTION_LOGS:
            await self._show_watcher_logs(message, userbot_id)
            return False, None

        return False, "❌ Pilih opsi yang tersedia."

    async def _show_watcher_logs(self, message: Message, userbot_id: int) -> None:
        rows = [row for row in fetch_userbot_tasks(userbot_id) if row["command"] == "watcher"]
        if not rows:
            info = "Belum ada task Watcher untuk userbot ini."
            reply_markup = self.make_keyboard([[ACTION_CREATE], [ACTION_LOGS]])
            await message.reply_text(info, reply_markup=reply_markup)
            self.log_out(message.from_user.id, info)
            return

        status_icon = {
            "pending": "⏳",
            "running": "🟡",
            "completed": "✅",
            "error": "❌",
            "stopped": "⛔",
        }

        lines: list[str] = ["📜 Watcher Logs (maks 8 terbaru)"]
        for idx, row in enumerate(rows[:8], start=1):
            details = safe_json_loads(row["details"])
            label = details.get("label") or "(Tanpa label)"
            status = (row["status"] or "").lower()
            icon = status_icon.get(status, "ℹ️")
            match_count = details.get("match_count", 0)
            last_match_at = details.get("last_match_at")
            last_sheet_append = details.get("last_sheet_append")
            last_sheet_error = details.get("last_sheet_error")
            last_sheet_error_at = details.get("last_sheet_error_at")
            note = details.get("last_status_note")
            destination = details.get("destination", {})
            dest_desc = "Local log"
            if destination.get("mode") == "sheets":
                resolved = destination.get("resolved", {})
                title = resolved.get("spreadsheet_title") or destination.get("sheet_ref") or "Sheets"
                worksheet = resolved.get("worksheet_title") or "Sheet1"
                dest_desc = f"Sheets ({title} / {worksheet})"

            lines.append(f"{idx}. {icon} {row['process_id']} — {label}")
            lines.append(f"   • Status: {status.upper()} | Target log: {dest_desc}")
            lines.append(f"   • Total hit: {match_count}{' (terakhir ' + last_match_at + ')' if last_match_at else ''}")
            if last_sheet_append:
                lines.append(f"   • Update Sheets terakhir: {last_sheet_append}")
            if last_sheet_error:
                when = f" pada {last_sheet_error_at}" if last_sheet_error_at else ""
                lines.append(f"   • Error Sheets: {last_sheet_error}{when}")
            if note:
                lines.append(f"   • Catatan sistem: {note}")

        reply_markup = self.make_keyboard([[ACTION_CREATE], [ACTION_LOGS]])
        response = "\n".join(lines)
        await message.reply_text(response, reply_markup=reply_markup)
        self.log_out(message.from_user.id, response)

    async def _handle_scope_choice(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE, userbot_id: int
    ) -> tuple[bool, str | None]:
        text = (message.text or "").strip()
        state = self.get_state(context)

        if text == SCOPE_ALL_GROUPS:
            targets = [int(row["telegram_group_id"]) for row in fetch_userbot_groups(userbot_id, "group")]
            if not targets:
                return False, "❌ Tidak ada grup yang tersinkron. Jalankan 📂 Sync Users Groups terlebih dahulu."
            state.update({"scope": "all_groups", "targets": targets})
            state["step"] = "collect_keywords"
            await self._send_keywords_prompt(message)
            return False, None

        if text == SCOPE_ALL_CHANNELS:
            targets = [int(row["telegram_group_id"]) for row in fetch_userbot_groups(userbot_id, "channel")]
            if not targets:
                return False, "❌ Tidak ada channel yang tersinkron. Jalankan 📂 Sync Users Groups terlebih dahulu."
            state.update({"scope": "all_channels", "targets": targets})
            state["step"] = "collect_keywords"
            await self._send_keywords_prompt(message)
            return False, None

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
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
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
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
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
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        text = (message.text or "").strip()
        state = self.get_state(context)

        if text == KEYWORD_MATCH_RELAXED:
            state["keyword_match_type"] = "contains"
        elif text == KEYWORD_MATCH_SPECIFIC:
            state["keyword_match_type"] = "specific"
        else:
            reminder = "❌ Jawab pakai tombol yang muncul di bawah ya."
            await message.reply_text(reminder, reply_markup=self.make_keyboard([[KEYWORD_MATCH_SPECIFIC], [KEYWORD_MATCH_RELAXED]]))
            self.log_out(message.from_user.id, reminder)
            return False, None

        state["step"] = "choose_keyword_logic"
        await self._send_keyword_logic_prompt(message)
        return False, None

    async def _handle_keyword_logic(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        text = (message.text or "").strip()
        state = self.get_state(context)

        if text == KEYWORD_LOGIC_ANY:
            state["keyword_logic"] = "any"
        elif text == KEYWORD_LOGIC_ALL:
            state["keyword_logic"] = "all"
        else:
            reminder = "❌ Tinggal pilih salah satu tombol supaya wizard mengerti."
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
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        text = (message.text or "").strip()
        state = self.get_state(context)

        if text == OPTION_SKIP_EXCLUSION:
            state["exclusions"] = []
            state["exclusion_match_type"] = "contains"
            state["exclusion_logic"] = "any"
            state["step"] = "choose_destination"
            await self._send_destination_prompt(message)
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

        reminder = "❌ Pilih opsi yang tersedia lewat tombol ya."
        await message.reply_text(reminder, reply_markup=self.make_keyboard([[OPTION_ADD_EXCLUSION, OPTION_SKIP_EXCLUSION]]))
        self.log_out(message.from_user.id, reminder)
        return False, None

    async def _handle_exclusion_input(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
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
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        text = (message.text or "").strip()
        state = self.get_state(context)

        if text == EXCLUSION_MATCH_RELAXED:
            state["exclusion_match_type"] = "contains"
        elif text == EXCLUSION_MATCH_SPECIFIC:
            state["exclusion_match_type"] = "specific"
        else:
            reminder = "❌ Jawabnya pakai tombol yang ada ya."
            await message.reply_text(reminder, reply_markup=self.make_keyboard([[EXCLUSION_MATCH_SPECIFIC], [EXCLUSION_MATCH_RELAXED]]))
            self.log_out(message.from_user.id, reminder)
            return False, None

        state["step"] = "choose_exclusion_logic"
        await self._send_exclusion_logic_prompt(message)
        return False, None

    async def _handle_exclusion_logic(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
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

        state["step"] = "choose_destination"
        await self._send_destination_prompt(message)
        return False, None

    async def _handle_destination_choice(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        choice = (message.text or "").strip()
        state = self.get_state(context)

        if choice == DEST_LOCAL:
            state["destination"] = {"mode": "local", "sheet_ref": None}
            state["step"] = "collect_label"
            await self._send_label_prompt(message)
            return False, None

        if choice == DEST_SHEETS:
            state["destination"] = {"mode": "sheets", "sheet_ref": None}
            state["step"] = "collect_sheet"
            instructions = (
                "Masukkan ID atau URL Google Sheets tujuan.\n"
                "Setup cepat:"
                "\n1. Aktifkan Google Sheets API dan buat Service Account."
                "\n2. Simpan file JSON kredensial ke `credentials/service_account.json`."
                "\n3. Bagikan Sheet ke email Service Account (akses editor)."
                "\nMasukkan ID/URL di sini (contoh: `1AbCdEf...`)."
            )
            reply_markup = self.make_keyboard()
            await message.reply_text(instructions, reply_markup=reply_markup)
            self.log_out(message.from_user.id, instructions)
            return False, None

        return False, "❌ Pilih salah satu opsi tujuan pencatatan."

    async def _handle_sheet_input(
        self, message: Message, context: ContextTypes.DEFAULT_TYPE
    ) -> tuple[bool, str | None]:
        sheet_ref = (message.text or "").strip()
        if not sheet_ref:
            return False, "❌ Masukkan ID atau URL Google Sheets yang valid."

        state = self.get_state(context)
        destination = state.get("destination", {"mode": "sheets"})
        destination["sheet_ref"] = sheet_ref
        state["destination"] = destination
        state["step"] = "collect_label"
        await self._send_label_prompt(message)
        return False, None

    async def _handle_label(
        self,
        message: Message,
        context: ContextTypes.DEFAULT_TYPE,
        userbot_id: int,
    ) -> tuple[bool, str | None]:
        label = (message.text or "").strip() or "Watcher"

        state = self.get_state(context)
        targets = state.get("targets", [])
        keywords = state.get("keywords", [])
        exclusions = state.get("exclusions", [])
        scope = state.get("scope", "custom")
        destination = state.get("destination", {"mode": "local", "sheet_ref": None})
        keyword_match_type = state.get("keyword_match_type", "contains")
        keyword_logic = state.get("keyword_logic", "any")
        exclusion_match_type = state.get("exclusion_match_type", "contains")
        exclusion_logic = state.get("exclusion_logic", "any")

        details = {
            "targets": targets,
            "keywords": keywords,
            "exclusions": exclusions,
            "destination": destination,
            "label": label,
            "scope": scope,
            "keyword_match_type": keyword_match_type,
            "keyword_logic": keyword_logic,
            "exclusion_match_type": exclusion_match_type,
            "exclusion_logic": exclusion_logic,
        }

        process_id, task_id = create_task(userbot_id, "watcher", details)
        self.reset(context)

        scope_desc = self._describe_scope(scope, len(targets))
        dest_desc = "Google Sheets" if destination.get("mode") == "sheets" else "Local log"
        if destination.get("sheet_ref"):
            dest_desc += f" ({destination['sheet_ref']})"

        summary_lines = [
            "✅ Watcher siap dijalankan!",
            f"• Task ID: {task_id}",
            f"• Process ID: `{process_id}`",
            f"• Scope: {scope_desc}",
            f"• Kata kunci: {', '.join(keywords)}",
            f"• Tujuan pencatatan: {dest_desc}",
            f"• Label: {label}",
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
        summary_lines.append("Userbot akan mulai memantau pesan baru dan mencatat hasilnya.")
        summary = "\n".join(summary_lines)
        return True, summary

    # ------------------------------------------------------------------
    async def _send_keywords_prompt(self, message: Message) -> None:
        prompt = (
            "Langkah berikut — tuliskan kata yang mau dipantau.\n"
            "• Pisahkan dengan koma jika lebih dari satu (contoh: `need,nit`).\n"
            "• Bisa langsung tambahkan `tanpa ...` di belakang untuk membuat larangan (contoh: `need,nit tanpa spam`)."
        )
        reply_markup = self.make_keyboard()
        await message.reply_text(prompt, reply_markup=reply_markup, parse_mode="Markdown")
        self.log_out(message.from_user.id, prompt)

    async def _send_keyword_match_type_prompt(self, message: Message) -> None:
        options = [[KEYWORD_MATCH_SPECIFIC], [KEYWORD_MATCH_RELAXED]]
        reply_markup = self.make_keyboard(options)
        prompt = (
            "Cara cek kata yang cocok mau seperti apa?\n"
            "• `Spesifik (kata harus utuh)` supaya `nit` tidak kena `menit`.\n"
            "• `Boleh potongan kata` kalau cukup ada sebagian katanya."
        )
        await message.reply_text(prompt, reply_markup=reply_markup)
        self.log_out(message.from_user.id, prompt)

    async def _send_keyword_logic_prompt(self, message: Message) -> None:
        options = [[KEYWORD_LOGIC_ANY], [KEYWORD_LOGIC_ALL]]
        reply_markup = self.make_keyboard(options)
        prompt = (
            "Kalau ada banyak kata, apakah semua harus muncul?\n"
            "• `Minimal satu kata cocok` = mode ATAU.\n"
            "• `Semua kata harus muncul` = mode DAN."
        )
        await message.reply_text(prompt, reply_markup=reply_markup)
        self.log_out(message.from_user.id, prompt)

    async def _send_exclusion_match_type_prompt(self, message: Message) -> None:
        options = [[EXCLUSION_MATCH_SPECIFIC], [EXCLUSION_MATCH_RELAXED]]
        reply_markup = self.make_keyboard(options)
        prompt = (
            "Pilih cara membaca kata larangan.\n"
            "• `Kata larangan harus utuh` supaya potongan kata lain tidak ikut diblok.\n"
            "• `Kata larangan boleh potongan` kalau cukup kena sebagian kata."
        )
        await message.reply_text(prompt, reply_markup=reply_markup)
        self.log_out(message.from_user.id, prompt)

    async def _send_exclusion_logic_prompt(self, message: Message) -> None:
        options = [[EXCLUSION_LOGIC_ANY], [EXCLUSION_LOGIC_ALL]]
        reply_markup = self.make_keyboard(options)
        prompt = (
            "Kapan watcher harus mengabaikan pesan?\n"
            "• `Stop jika salah satu muncul` = cukup satu kata larangan.\n"
            "• `Stop jika semua muncul` = semua kata larangan harus ada."
        )
        await message.reply_text(prompt, reply_markup=reply_markup)
        self.log_out(message.from_user.id, prompt)

    async def _send_destination_prompt(self, message: Message) -> None:
        options = [[DEST_LOCAL, DEST_SHEETS]]
        prompt = (
            "Pilih tujuan pencatatan hasil watcher.\n"
            "`🗂 Local Log` (default) atau `📄 Google Sheets`."
        )
        reply_markup = self.make_keyboard(options)
        await message.reply_text(prompt, reply_markup=reply_markup, parse_mode="Markdown")
        self.log_out(message.from_user.id, prompt)

    async def _send_label_prompt(self, message: Message) -> None:
        prompt = "Berikan nama/label untuk watcher ini (contoh: `Prospek Harian`)."
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


def build_command(deps: CommandDependencies) -> WatcherCommand:
    return WatcherCommand(deps)
