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
        details = ctx.details or {}
        scope = str(details.get('testing_scope') or 'all').lower()
        raw_targets = details.get('testing_targets')
        if not isinstance(raw_targets, list):
            raw_targets = []

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
            target_pool = self._resolve_target_pool(ctx.userbot_id, scope, raw_targets)
            if not target_pool:
                raise RuntimeError('No chat targets available for automated testing.')

            await self._run_auto_reply(ctx, record, target_pool, scope)
            await self._run_watcher(ctx, record, target_pool, scope)
            await self._run_broadcast(ctx, record, target_pool, scope)
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

    async def _run_auto_reply(self, ctx: CommandContext, record, target_pool: List[int], scope: str) -> None:
        if not target_pool:
            raise RuntimeError('No chats available for auto-reply dry run.')

        cases = [
            {
                'label': 'contains_any',
                'keywords': ['autotest', 'little ghost'],
                'keyword_match_type': 'contains',
                'keyword_logic': 'any',
                'exclusions': ['ignore_me'],
                'exclusion_match_type': 'contains',
                'exclusion_logic': 'any',
            },
            {
                'label': 'specific_all',
                'keywords': ['ghost crew', 'ready'],
                'keyword_match_type': 'specific',
                'keyword_logic': 'all',
                'exclusions': ['skip'],
                'exclusion_match_type': 'specific',
                'exclusion_logic': 'all',
            },
        ]

        for idx, case in enumerate(cases, start=1):
            target = target_pool[min(idx - 1, len(target_pool) - 1)]
            details = {
                'targets': [target],
                'keywords': case['keywords'],
                'exclusions': case['exclusions'],
                'reply_text': f"[AUTOTEST {case['label']}] response 👻",
                'scope': 'custom',
                'keyword_match_type': case['keyword_match_type'],
                'keyword_logic': case['keyword_logic'],
                'exclusion_match_type': case['exclusion_match_type'],
                'exclusion_logic': case['exclusion_logic'],
            }
            note = f"Case {idx}: {case['label']} → chat {target}"
            await record('auto_reply', 'running', note, {'case': case, 'scope': scope})
            sub_ctx = self._sub_context(ctx, f"auto_test.auto_reply.{case['label']}", details)
            handle = await self._registry['auto_reply'].start(sub_ctx)
            if handle:
                await asyncio.sleep(2)
                await self._registry['auto_reply'].stop(handle, sub_ctx)
            await record('auto_reply', 'completed', f"Case {idx}: {case['label']} selesai")

    async def _run_watcher(self, ctx: CommandContext, record, target_pool: List[int], scope: str) -> None:
        if not target_pool:
            raise RuntimeError('No chats available for watcher dry run.')

        cases = [
            {
                'label': 'contains_any',
                'keywords': ['watch_me', 'alert'],
                'keyword_match_type': 'contains',
                'keyword_logic': 'any',
                'exclusions': ['mute'],
                'exclusion_match_type': 'contains',
                'exclusion_logic': 'any',
            },
            {
                'label': 'specific_all',
                'keywords': ['alert', 'team'],
                'keyword_match_type': 'specific',
                'keyword_logic': 'all',
                'exclusions': ['mute', 'later'],
                'exclusion_match_type': 'specific',
                'exclusion_logic': 'all',
            },
        ]

        for idx, case in enumerate(cases, start=1):
            target = target_pool[min(idx - 1, len(target_pool) - 1)]
            details = {
                'targets': [target],
                'keywords': case['keywords'],
                'exclusions': case['exclusions'],
                'destination': {'mode': 'local', 'sheet_ref': None},
                'label': f"AutoTest Watcher {case['label']}",
                'scope': 'custom',
                'keyword_match_type': case['keyword_match_type'],
                'keyword_logic': case['keyword_logic'],
                'exclusion_match_type': case['exclusion_match_type'],
                'exclusion_logic': case['exclusion_logic'],
            }
            note = f"Case {idx}: {case['label']} → chat {target}"
            await record('watcher', 'running', note, {'case': case, 'scope': scope})
            sub_ctx = self._sub_context(ctx, f"auto_test.watcher.{case['label']}", details)
            handle = await self._registry['watcher'].start(sub_ctx)
            if handle:
                await asyncio.sleep(2)
                await self._registry['watcher'].stop(handle, sub_ctx)
            await record('watcher', 'completed', f"Case {idx}: {case['label']} selesai")

    async def _run_broadcast(self, ctx: CommandContext, record, target_pool: List[int], scope: str) -> None:
        if not target_pool:
            raise RuntimeError('No chats available for broadcast dry run.')

        targets = target_pool[:3] or [target_pool[0]]
        details = {
            'mode': 'manual',
            'content': {'type': 'text', 'text': '[AUTOTEST] broadcast ping'},
            'schedule': {'mode': 'now', 'minutes': 0},
            'targets': targets,
            'scope': 'custom',
        }
        await record('broadcast', 'running', f"Targets: {len(targets)}", {'scope': scope})
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

    def _resolve_target_pool(self, userbot_id: int, scope: str, raw_targets: List[Any]) -> List[int]:
        if scope == 'custom':
            targets: List[int] = []
            for item in raw_targets or []:
                try:
                    targets.append(int(item))
                except (TypeError, ValueError):
                    continue
            return targets

        groups = self._fetch_groups(userbot_id)
        return [int(row['telegram_group_id']) for row in groups]


def build_command(registry: Dict[str, UserbotCommand]) -> UserbotCommand:
    return AutomatedTestingCommand(registry)
