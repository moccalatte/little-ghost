"""Automated testing routine for Little Ghost userbot."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List

from core.infra.database import get_db_connection

from services.userbot.commands.base import ActiveCommand, CommandContext, UserbotCommand


class AutomatedTestingCommand(UserbotCommand):
    def __init__(self, registry: Dict[str, UserbotCommand]) -> None:
        super().__init__(slug="auto_test")
        self._registry = registry

    async def start(self, ctx: CommandContext) -> ActiveCommand | None:
        logger = ctx.logger
        await ctx.update_status('running', 'Automated testing started')
        results: List[Dict[str, Any]] = []

        async def record(step: str, status: str, note: str | None = None, extra: Dict[str, Any] | None = None) -> None:
            entry = {
                'step': step,
                'status': status,
                'note': note,
                'timestamp': datetime.utcnow().isoformat(),
            }
            if extra:
                entry.update(extra)
            results.append(entry)
            await ctx.refresh_task_details({'auto_test': results})
            message = f"[{step}] {status.upper()}"
            if note:
                message += f" — {note}"
            logger.info(message)
            if extra:
                logger.debug("[%s] context=%s", step, json.dumps(extra, ensure_ascii=False))

        try:
            await self._prepare_groups(ctx, record)
            await self._run_auto_reply(ctx, record)
            await self._run_watcher(ctx, record)
            await self._run_broadcast(ctx, record)
            await self._snapshot_tasks(ctx, record)
            await ctx.update_status('completed', 'Automated testing finished')
            logger.info("Automated testing finished successfully.")
        except Exception as exc:  # pragma: no cover - integration heavy
            logger.exception("Automated testing failed: %s", exc)
            await ctx.update_status('error', str(exc))
            await record('auto_test', 'error', str(exc))
        return None

    async def _prepare_groups(self, ctx: CommandContext, record) -> None:
        logger = ctx.logger
        groups = self._fetch_groups(ctx.userbot_id)
        if groups:
            await record('sync_groups', 'skipped', f"Reuse {len(groups)} cached groups")
            return

        await record('sync_groups', 'running', 'Refreshing group list from Telegram')
        await self._registry['sync_groups'].start(self._sub_context(ctx, 'auto_test.sync_groups', {}))
        groups = self._fetch_groups(ctx.userbot_id)
        await record('sync_groups', 'completed', f"Synced {len(groups)} groups")
        logger.info("[auto_test] Synced %s groups", len(groups))

    async def _run_auto_reply(self, ctx: CommandContext, record) -> None:
        groups = self._fetch_groups(ctx.userbot_id)
        if not groups:
            raise RuntimeError('No groups available for auto-reply dry run.')
        target = int(groups[0]['telegram_group_id'])
        keywords = ['autotest', 'little ghost']
        details = {
            'targets': [target],
            'keywords': keywords,
            'exclusions': ['ignore_me'],
            'reply_text': 'Automated test response 👻',
            'scope': 'custom',
        }
        await record('auto_reply', 'running', f"Target chat {target}")
        sub_ctx = self._sub_context(ctx, 'auto_test.auto_reply', details)
        handle = await self._registry['auto_reply'].start(sub_ctx)
        if handle:
            await asyncio.sleep(2)
            await self._registry['auto_reply'].stop(handle, sub_ctx)
        await record('auto_reply', 'completed', f"Keywords: {', '.join(keywords)}")

    async def _run_watcher(self, ctx: CommandContext, record) -> None:
        groups = self._fetch_groups(ctx.userbot_id)
        if not groups:
            raise RuntimeError('No groups available for watcher dry run.')
        target = int(groups[-1]['telegram_group_id'])
        details = {
            'targets': [target],
            'keywords': ['watch_me', 'alert'],
            'exclusions': ['mute'],
            'destination': {'mode': 'local', 'sheet_ref': None},
            'label': 'AutoTest Watcher',
            'scope': 'custom',
        }
        await record('watcher', 'running', f"Target chat {target}")
        sub_ctx = self._sub_context(ctx, 'auto_test.watcher', details)
        handle = await self._registry['watcher'].start(sub_ctx)
        if handle:
            await asyncio.sleep(2)
            await self._registry['watcher'].stop(handle, sub_ctx)
        await record('watcher', 'completed', 'Watcher active for dry run')

    async def _run_broadcast(self, ctx: CommandContext, record) -> None:
        groups = self._fetch_groups(ctx.userbot_id)
        targets = [int(row['telegram_group_id']) for row in groups[:3]] or [0]
        details = {
            'mode': 'manual',
            'content': {'type': 'text', 'text': '[AUTOTEST] broadcast ping'},
            'schedule': {'mode': 'now', 'minutes': 0},
            'targets': targets,
            'scope': 'custom',
        }
        await record('broadcast', 'running', f"Targets: {len(targets)}")
        sub_ctx = self._sub_context(ctx, 'auto_test.broadcast', details)
        await self._registry['broadcast'].start(sub_ctx)
        await record('broadcast', 'completed', 'Dry run completed')

    async def _snapshot_tasks(self, ctx: CommandContext, record) -> None:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT process_id, command, status, details FROM tasks WHERE userbot_id = ? ORDER BY id DESC LIMIT 10",
                (ctx.userbot_id,),
            ).fetchall()
        finally:
            conn.close()
        snapshot = [
            {
                'process_id': row['process_id'],
                'command': row['command'],
                'status': row['status'],
                'details': row['details'],
            }
            for row in rows
        ]
        await record('task_snapshot', 'completed', extra={'tasks': snapshot})

    def _sub_context(self, base_ctx: CommandContext, suffix: str, details: Dict[str, Any]) -> CommandContext:
        async def _noop_status(status: str, note: str | None) -> None:
            base_ctx.logger.debug("[%s] status=%s note=%s", suffix, status, note)

        async def _noop_refresh(_: Dict[str, Any]) -> None:
            return

        return CommandContext(
            userbot_id=base_ctx.userbot_id,
            process_id=f"{base_ctx.process_id}:{suffix}",
            task_id=base_ctx.task_id,
            details=details,
            client=base_ctx.client,
            job_logger=base_ctx.logger,
            update_status=_noop_status,
            refresh_task_details=_noop_refresh,
        )

    @staticmethod
    def _fetch_groups(userbot_id: int) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT telegram_group_id, group_name FROM groups WHERE userbot_id = ? ORDER BY group_name",
                (userbot_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


def build_command(registry: Dict[str, UserbotCommand]) -> UserbotCommand:
    return AutomatedTestingCommand(registry)
