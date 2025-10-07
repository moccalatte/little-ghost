"""Sync groups/channels command for admin workflows."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from telethon.tl.types import Dialog

from core.infra.database import get_db_connection

from services.userbot.commands.base import CommandContext, UserbotCommand

SYNC_LOG_DIR = Path("logs/admin")
PAGE_SIZE = 50


class SyncGroupsCommand(UserbotCommand):
    def __init__(self) -> None:
        super().__init__(slug="sync_groups")

    async def start(self, ctx: CommandContext) -> None:
        logger = ctx.logger
        logger.info("Memulai sinkronisasi grup/kanal untuk userbot %s", ctx.userbot_id)

        dialogs: List[Dialog] = await ctx.client.get_dialogs()
        relevant_dialogs = [dialog for dialog in dialogs if dialog.is_group or dialog.is_channel]
        total = len(relevant_dialogs)
        logger.info("Ditemukan %s dialog relevan untuk disinkronkan.", total)

        entries: List[Dict[str, object]] = []
        for index, dialog in enumerate(relevant_dialogs, start=1):
            entity = dialog.entity
            group_type = 'channel' if dialog.is_channel and not dialog.is_group else 'group'
            entries.append({
                'userbot_id': ctx.userbot_id,
                'telegram_group_id': dialog.id,
                'group_name': dialog.name,
                'access_hash': getattr(entity, 'access_hash', None),
                'group_type': group_type,
                'username': getattr(entity, 'username', None),
            })

            if index % PAGE_SIZE == 0 or index == total:
                page = (index - 1) // PAGE_SIZE + 1
                total_pages = (total - 1) // PAGE_SIZE + 1 if total else 1
                logger.info("⏳ Sinkronisasi halaman %s/%s", page, total_pages)

        await self._persist_entries(ctx, entries)
        await self._update_sync_log(ctx, entries)

        await ctx.refresh_task_details({'synced_items': len(entries)})
        await ctx.update_status('completed', None)
        logger.info("Sinkronisasi selesai: %s entri diperbarui untuk userbot %s.", len(entries), ctx.userbot_id)

    async def _persist_entries(self, ctx: CommandContext, entries: List[Dict[str, object]]) -> None:
        me = await ctx.client.get_me()
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM groups WHERE userbot_id = ?", (ctx.userbot_id,))
            if entries:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO groups (userbot_id, telegram_group_id, group_name, access_hash, group_type, username)
                    VALUES (:userbot_id, :telegram_group_id, :group_name, :access_hash, :group_type, :username)
                    """,
                    entries,
                )
            conn.execute(
                "UPDATE userbots SET telegram_id = ?, username = ?, status = 'active' WHERE id = ?",
                (getattr(me, 'id', None), getattr(me, 'username', None), ctx.userbot_id),
            )
            conn.commit()
        finally:
            conn.close()

    async def _update_sync_log(self, ctx: CommandContext, entries: List[Dict[str, object]]) -> None:
        me = await ctx.client.get_me()
        telegram_user_id = getattr(me, 'id', None) or ctx.userbot_id
        SYNC_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = SYNC_LOG_DIR / f"sync_{telegram_user_id}.log"

        existing_ids: set[int] = set()
        if log_path.exists():
            try:
                with log_path.open('r', encoding='utf-8') as fh:
                    for line in fh:
                        try:
                            data = json.loads(line)
                            existing_ids.add(int(data['telegram_group_id']))
                        except (KeyError, ValueError, json.JSONDecodeError):
                            continue
            except OSError as exc:  # pragma: no cover - filesystem issues
                ctx.logger.warning("Gagal membaca log sinkronisasi %s: %s", log_path, exc)

        new_entries = 0
        try:
            with log_path.open('a', encoding='utf-8') as fh:
                for entry in entries:
                    chat_id = int(entry['telegram_group_id'])
                    if chat_id in existing_ids:
                        continue
                    record = {
                        'telegram_group_id': chat_id,
                        'username': entry.get('username'),
                        'name': entry.get('group_name'),
                        'type': entry.get('group_type'),
                        'sync_timestamp': datetime.utcnow().isoformat(),
                    }
                    fh.write(json.dumps(record, ensure_ascii=False) + '\n')
                    existing_ids.add(chat_id)
                    new_entries += 1
        except OSError as exc:  # pragma: no cover - filesystem issues
            ctx.logger.warning("Gagal menulis log sinkronisasi %s: %s", log_path, exc)

        ctx.logger.info("Log sinkronisasi diperbarui: %s entri baru.", new_entries)


def build_command() -> UserbotCommand:
    return SyncGroupsCommand()
