"""Watcher command implementation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Callable, List, Optional

from telethon import events

from core.infra.google_sheets import (
    GoogleSheetsCredentialsError,
    GoogleSheetsError,
    GoogleSheetsNotFoundError,
    GoogleSheetsPermissionError,
    GoogleSheetsRecorder,
)

from .base import ActiveCommand, CommandContext, UserbotCommand


@dataclass
class _WatcherState:
    keywords: List[str]
    exclusions: List[str]
    destination: dict
    label: str
    keyword_match_type: str = "contains"
    keyword_logic: str = "any"
    exclusion_match_type: str = "contains"
    exclusion_logic: str = "any"
    counter: int = 0
    sheet_recorder: Optional[GoogleSheetsRecorder] = None
    _keyword_checks: List[Callable[[str, str], bool]] | None = None
    _exclusion_checks: List[Callable[[str, str], bool]] | None = None

    def __post_init__(self) -> None:
        self._keyword_checks = [self._make_checker(word, self.keyword_match_type) for word in self.keywords]
        self._exclusion_checks = [self._make_checker(word, self.exclusion_match_type) for word in self.exclusions]

    def _make_checker(self, word: str, mode: str) -> Callable[[str, str], bool]:
        if mode == "specific":
            pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
            return lambda original, _lowered: bool(pattern.search(original))
        lowered_word = word.lower()
        return lambda _original, lowered: lowered_word in lowered

    def match(self, text: str) -> bool:
        lowered = text.lower()
        keyword_hits = [check(text, lowered) for check in (self._keyword_checks or [])]
        if not keyword_hits:
            return False

        if self.keyword_logic == "all":
            keywords_ok = all(keyword_hits)
        else:
            keywords_ok = any(keyword_hits)

        if not keywords_ok:
            return False

        if not self._exclusion_checks:
            return True

        exclusion_hits = [check(text, lowered) for check in self._exclusion_checks]
        if self.exclusion_logic == "all":
            blocked = all(exclusion_hits)
        else:
            blocked = any(exclusion_hits)

        return not blocked


class WatcherCommand(UserbotCommand):
    def __init__(self) -> None:
        super().__init__(slug="watcher")

    async def start(self, ctx: CommandContext) -> ActiveCommand | None:
        details = ctx.details
        logger = ctx.logger
        targets = details.get("targets") or []
        keywords = [str(item).strip().lower() for item in details.get("keywords", []) if str(item).strip()]
        exclusions = [str(item).strip().lower() for item in details.get("exclusions", []) if str(item).strip()]
        destination = details.get("destination") or {"mode": "local", "sheet_ref": None}
        label = details.get("label") or f"Watcher {ctx.process_id}" if ctx.process_id else "Watcher"
        keyword_match_type = str(details.get("keyword_match_type") or "contains").lower()
        keyword_logic = str(details.get("keyword_logic") or "any").lower()
        exclusion_match_type = str(details.get("exclusion_match_type") or "contains").lower()
        exclusion_logic = str(details.get("exclusion_logic") or "any").lower()

        if not targets or not keywords:
            logger.error("Data watcher tidak valid. targets=%s keywords=%s", targets, keywords)
            await ctx.update_status("error", "Watcher tidak memiliki target atau kata kunci.")
            return None

        sheet_recorder: Optional[GoogleSheetsRecorder] = None
        if destination.get("mode") == "sheets":
            sheet_ref = str(destination.get("sheet_ref") or "").strip()
            if not sheet_ref:
                note = "Tujuan Google Sheets belum diisi."
                logger.error("Watcher '%s' gagal: %s", label, note)
                await ctx.update_status("error", note)
                return None

            try:
                sheet_recorder = await GoogleSheetsRecorder.create(sheet_ref)
                await sheet_recorder.ensure_header(
                    (
                        "username_pengirim",
                        "telegram_id_pengirim",
                        "pesan",
                        "nama_grup",
                        "timestamp_utc",
                        "process_id",
                        "label",
                        "id_chat",
                        "message_id",
                    )
                )
            except GoogleSheetsCredentialsError as exc:
                note = "Kredensial Google Sheets belum tersedia atau tidak valid."
                logger.error("Watcher '%s' gagal memuat kredensial: %s", label, exc)
                await ctx.update_status("error", note)
                return None
            except GoogleSheetsPermissionError as exc:
                note = "Service account tidak memiliki akses ke Sheet yang dipilih."
                logger.error("Watcher '%s' tidak memiliki izin akses sheet: %s", label, exc)
                await ctx.update_status("error", note)
                return None
            except GoogleSheetsNotFoundError as exc:
                note = "Google Sheet atau worksheet tidak ditemukan."
                logger.error("Watcher '%s' gagal menemukan sheet: %s", label, exc)
                await ctx.update_status("error", note)
                return None
            except GoogleSheetsError as exc:
                note = "Gagal menginisialisasi koneksi Google Sheets."
                logger.error("Watcher '%s' gagal menginisialisasi sheets: %s", label, exc)
                await ctx.update_status("error", note)
                return None

            resolved = destination.setdefault("resolved", {})
            resolved.update(
                {
                    "spreadsheet_title": sheet_recorder.spreadsheet_title,
                    "worksheet_title": sheet_recorder.worksheet_title,
                    "spreadsheet_id": sheet_recorder.spreadsheet_id,
                    "worksheet_id": sheet_recorder.worksheet_id,
                }
            )
            await ctx.refresh_task_details({"destination": destination})
            logger.info(
                "Watcher '%s' menulis ke Google Sheets '%s' / '%s' (process_id=%s)",
                label,
                sheet_recorder.spreadsheet_title,
                sheet_recorder.worksheet_title,
                ctx.process_id,
            )

        state = _WatcherState(
            keywords=keywords,
            exclusions=exclusions,
            destination=destination,
            label=label,
            keyword_match_type="specific" if keyword_match_type == "specific" else "contains",
            keyword_logic="all" if keyword_logic == "all" else "any",
            exclusion_match_type="specific" if exclusion_match_type == "specific" else "contains",
            exclusion_logic="all" if exclusion_logic == "all" else "any",
            sheet_recorder=sheet_recorder,
        )
        handler = events.NewMessage(chats=targets)

        async def _on_message(event: events.NewMessage.Event) -> None:
            if event.out:
                return
            message_text = event.raw_text or ""
            if not message_text:
                return
            if not state.match(message_text):
                return

            state.counter += 1
            record_time = datetime.now(ZoneInfo("Asia/Jakarta")).isoformat()
            ctx.logger.info(
                "Watcher match #%s at %s | chat=%s message_id=%s | pesan=%s",
                state.counter,
                record_time,
                event.chat_id,
                event.id,
                message_text[:200],
            )
            updates: dict[str, str | int] = {
                "match_count": state.counter,
                "last_match_at": record_time,
            }

            if state.sheet_recorder:
                chat_name = ""
                try:
                    chat = await event.get_chat()
                    chat_name = getattr(chat, "title", None) or getattr(chat, "username", None) or ""
                except Exception:  # pragma: no cover - jaringan
                    chat_name = ""

                sender_id = getattr(event, "sender_id", None)
                username = ""
                try:
                    sender = await event.get_sender()
                    username = getattr(sender, "username", None) or ""
                    if not username:
                        first_name = getattr(sender, "first_name", None) or ""
                        last_name = getattr(sender, "last_name", None) or ""
                        combined = (first_name + " " + last_name).strip()
                        username = combined or ""
                except Exception:  # pragma: no cover - jaringan
                    username = ""

                row = [
                    username,
                    str(sender_id) if sender_id is not None else "",
                    message_text,
                    chat_name,
                    record_time,
                    ctx.process_id or "",
                    state.label,
                    str(event.chat_id),
                    str(event.id),
                ]

                try:
                    await state.sheet_recorder.append_row(row)
                except GoogleSheetsError as exc:
                    ctx.logger.error("Gagal menulis ke Google Sheets: %s", exc)
                    updates.update(
                        {
                            "last_sheet_error": str(exc),
                            "last_sheet_error_at": record_time,
                        }
                    )
                else:
                    updates["last_sheet_append"] = record_time
                    ctx.logger.info(
                        "Watcher mencatat match #%s ke Google Sheets baris baru.",
                        state.counter,
                    )

            await ctx.refresh_task_details(updates)

        ctx.client.add_event_handler(_on_message, handler)
        await ctx.update_status("running", None)
        logger.info(
            "Watcher '%s' aktif pada %s target dengan %s kata kunci (process_id=%s)",
            label,
            len(targets),
            len(keywords),
            ctx.process_id,
        )

        active = ActiveCommand()

        async def _remove_handler() -> None:
            try:
                ctx.client.remove_event_handler(_on_message, handler)
            except ValueError:
                pass

        active.add_stop_callback(_remove_handler)
        return active


def build_command() -> UserbotCommand:
    return WatcherCommand()
