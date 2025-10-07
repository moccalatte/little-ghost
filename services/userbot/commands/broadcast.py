"""Broadcast command implementation."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Dict, List

from .base import ActiveCommand, CommandContext, UserbotCommand


class BroadcastCommand(UserbotCommand):
    def __init__(self) -> None:
        super().__init__(slug="broadcast")

    async def start(self, ctx: CommandContext) -> ActiveCommand | None:
        details = ctx.details
        logger = ctx.logger

        targets: List[int] = details.get("targets") or []
        schedule = details.get("schedule") or {"mode": "now", "minutes": 0}
        content: Dict[str, str] = details.get("content") or {}
        mode = schedule.get("mode", "now")
        minutes = int(schedule.get("minutes", 0) or 0)
        dry_run = bool(details.get("dry_run"))

        if not targets or not content:
            logger.error("Broadcast tidak memiliki target atau konten yang valid. details=%s", details)
            await ctx.update_status("error", "Broadcast memerlukan target dan konten yang valid.")
            return None

        async def _send_once() -> dict:
            success = 0
            failures: List[int] = []
            for target in targets:
                try:
                    if dry_run:
                        logger.info("Broadcast dry-run ke %s (tidak mengirim konten).", target)
                    else:
                        await self._send_content(ctx, target, content)
                    success += 1
                except Exception as exc:  # pragma: no cover - jaringan
                    logger.warning("Gagal mengirim broadcast ke %s: %s", target, exc)
                    failures.append(target)
            timestamp = datetime.utcnow().isoformat()
            await ctx.refresh_task_details(
                {
                    "last_send": timestamp,
                    "last_success": success,
                    "last_failures": failures,
                    "content_type": content.get('type'),
                }
            )
            logger.info(
                "Broadcast%s terkirim %s/%s target pada %s (process_id=%s)",
                " (dry-run)" if dry_run else "",
                success,
                len(targets),
                timestamp,
                ctx.process_id,
            )
            return {"success": success, "failures": failures, "timestamp": timestamp}

        if mode == "now":
            await ctx.update_status("running", None)
            await _send_once()
            await ctx.update_status("completed", None)
            return None

        if mode == "delay":
            await ctx.update_status("scheduled", None)

            async def _delayed_delivery() -> None:
                await asyncio.sleep(max(minutes, 0) * 60)
                await ctx.update_status("running", None)
                await _send_once()
                await ctx.update_status("completed", None)

            task = asyncio.create_task(_delayed_delivery())
            active = ActiveCommand()
            active.register_task(task)
            return active

        if mode == "interval":
            interval_minutes = max(minutes, 1)
            await ctx.update_status("interval", None)

            async def _loop() -> None:
                delivery_count = 0
                while True:
                    await _send_once()
                    delivery_count += 1
                    await ctx.refresh_task_details({"delivery_count": delivery_count})
                    await asyncio.sleep(interval_minutes * 60)

            task = asyncio.create_task(_loop())
            active = ActiveCommand()
            active.register_task(task)
            return active

        logger.error("Mode broadcast tidak dikenal: %s", mode)
        await ctx.update_status("error", f"Mode jadwal '{mode}' tidak dikenali.")
        return None

    async def _send_content(self, ctx: CommandContext, target: int, content: Dict[str, str]) -> None:
        content_type = content.get("type")
        if content_type == "text":
            await ctx.client.send_message(target, content.get("text", ""))
            return

        if content_type == "photo":
            path = content.get("path")
            if not path or not os.path.exists(path):
                raise FileNotFoundError(f"File foto tidak ditemukan: {path}")
            await ctx.client.send_file(
                target,
                path,
                caption=content.get("caption"),
            )
            return

        if content_type == "document":
            path = content.get("path")
            if not path or not os.path.exists(path):
                raise FileNotFoundError(f"File dokumen tidak ditemukan: {path}")
            await ctx.client.send_file(
                target,
                path,
                caption=content.get("caption"),
                force_document=True,
            )
            return

        if content_type == "forward":
            from_chat_id = int(content.get("from_chat_id"))
            message_id = int(content.get("message_id"))
            await ctx.client.forward_messages(target, message_id, from_chat_id)
            return

        raise ValueError(f"Jenis konten broadcast tidak dikenal: {content_type}")


def build_command() -> UserbotCommand:
    return BroadcastCommand()
