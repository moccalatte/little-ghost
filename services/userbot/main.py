import os
import sys
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

from pkg.logger import setup_logger
from pkg.pid_manager import PIDManager
from core.infra.database import get_db_connection
from services.userbot.commands import build_command_registry
from services.userbot.commands.base import ActiveCommand, CommandContext, UserbotCommand

load_dotenv()

logger = setup_logger('userbot', 'task_runner')

API_ID_RAW = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')

missing_vars = [name for name, value in {
    'API_ID': API_ID_RAW,
    'API_HASH': API_HASH,
}.items() if not value]

if missing_vars:
    logger.critical("Variabel environment wajib belum diisi: %s", ', '.join(missing_vars))
    sys.exit(1)

try:
    API_ID = int(API_ID_RAW)
except (TypeError, ValueError):
    logger.critical("API_ID harus berupa angka valid.")
    sys.exit(1)

COMMAND_REGISTRY = build_command_registry()


class ClientManager:
    """Cache koneksi Telethon per userbot."""

    def __init__(self) -> None:
        self._clients: Dict[int, TelegramClient] = {}
        self._locks: Dict[int, asyncio.Lock] = {}

    async def get_client(self, userbot_id: int) -> TelegramClient:
        if userbot_id in self._clients:
            return self._clients[userbot_id]

        lock = self._locks.setdefault(userbot_id, asyncio.Lock())
        async with lock:
            if userbot_id in self._clients:
                return self._clients[userbot_id]

            session_value = self._fetch_session(userbot_id)
            client = TelegramClient(StringSession(session_value), API_ID, API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError("String session tidak valid atau kedaluwarsa.")

            self._clients[userbot_id] = client
            return client

    async def close_all(self) -> None:
        for client in list(self._clients.values()):
            try:
                await client.disconnect()
            except Exception:  # pragma: no cover - jaringan
                pass
        self._clients.clear()
        self._locks.clear()

    @staticmethod
    def _fetch_session(userbot_id: int) -> str:
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT string_session FROM userbots WHERE id = ?", (userbot_id,)).fetchone()
        finally:
            conn.close()

        if not row or not row['string_session']:
            raise RuntimeError(f"String session untuk userbot {userbot_id} tidak ditemukan.")
        return row['string_session']


@dataclass
class ActiveJob:
    command: UserbotCommand
    context: CommandContext
    handle: ActiveCommand


def create_job_logger(command: str, process_id: str) -> logging.Logger:
    """Buat logger khusus untuk setiap job userbot."""
    safe_process = process_id.replace('/', '_')
    logger_name = f"little_ghost.userbot.jobs.{command}.{safe_process}"
    job_logger = logging.getLogger(logger_name)

    if job_logger.hasHandlers():
        return job_logger

    job_logger.setLevel(logging.INFO)
    log_dir = Path('logs') / 'userbot' / 'jobs' / command
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{safe_process}.log"

    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] - %(message)s')
    file_handler.setFormatter(formatter)
    job_logger.addHandler(file_handler)

    # Biarkan propagate agar tetap muncul di log umum userbot
    job_logger.propagate = True
    return job_logger


class UserbotService:
    def __init__(self) -> None:
        self._client_manager = ClientManager()
        self._active_jobs: Dict[str, ActiveJob] = {}
        self._loop_delay = 2.0

    async def run(self) -> None:
        await self._recover_inflight_tasks()
        logger.info("Userbot task runner siap menerima instruksi.")

        try:
            while True:
                await self._process_pending_tasks()
                await self._process_stop_requests()
                await asyncio.sleep(self._loop_delay)
        finally:
            await self._client_manager.close_all()

    async def _process_pending_tasks(self) -> None:
        pending_rows = await asyncio.to_thread(self._fetch_pending_rows)
        for row in pending_rows:
            process_id = row['process_id']
            if process_id in self._active_jobs:
                continue
            command = COMMAND_REGISTRY.get(row['command'])
            if not command:
                await self._mark_task_error(row['id'], f"Command tidak dikenal: {row['command']}")
                continue
            try:
                await self._start_task(row, command)
            except Exception as exc:  # pragma: no cover - jaringan
                logger.exception("Gagal memulai task %s: %s", process_id, exc)
                await self._mark_task_error(row['id'], str(exc))

    async def _process_stop_requests(self) -> None:
        stop_rows = await asyncio.to_thread(self._fetch_stop_rows)
        if not stop_rows:
            return
        for row in stop_rows:
            process_id = row['process_id']
            job = self._active_jobs.pop(process_id, None)
            if not job:
                continue
            job.context.logger.info("Perintah dihentikan dari wizard.")
            await job.command.stop(job.handle, job.context)
            await job.context.refresh_task_details({'stopped_at': datetime.utcnow().isoformat()})
            # Status sudah diset oleh wizard, pastikan detail konsisten

    async def _start_task(self, row: Dict[str, Any], command: UserbotCommand) -> None:
        task_id = row['id']
        userbot_id = row['userbot_id']
        process_id = row['process_id']
        details = self._parse_details(row.get('details'))

        client = await self._client_manager.get_client(userbot_id)
        job_logger = create_job_logger(command.slug, process_id)

        async def update_status(status: str, note: Optional[str]) -> None:
            await self._update_task_status(task_id, status, note)

        async def refresh_details(data: Dict[str, Any]) -> None:
            await self._merge_task_details(task_id, data)

        ctx = CommandContext(
            userbot_id=userbot_id,
            process_id=process_id,
            task_id=task_id,
            details=details,
            client=client,
            job_logger=job_logger,
            update_status=update_status,
            refresh_task_details=refresh_details,
        )

        await ctx.update_status('running', None)
        job_logger.info("Menjalankan command '%s' (task_id=%s)", command.slug, task_id)

        active_handle = await command.start(ctx)
        if active_handle is None:
            job_logger.info("Command '%s' selesai tanpa job aktif.", command.slug)
            current_status = await self._get_task_status(task_id)
            if current_status not in {'completed', 'error', 'stopped'}:
                await ctx.update_status('completed', None)
            return

        self._active_jobs[process_id] = ActiveJob(command=command, context=ctx, handle=active_handle)
        self._attach_completion_callbacks(process_id, active_handle, ctx)

    def _attach_completion_callbacks(self, process_id: str, handle: ActiveCommand, ctx: CommandContext) -> None:
        for task in handle.tasks:
            task.add_done_callback(
                lambda completed, pid=process_id, context=ctx: asyncio.create_task(
                    self._on_background_task_done(pid, completed, context)
                )
            )

    async def _on_background_task_done(self, process_id: str, task: asyncio.Task, ctx: CommandContext) -> None:
        if task.cancelled():
            ctx.logger.info("Background task untuk %s dibatalkan.", process_id)
            return

        exc = task.exception()
        if exc:
            ctx.logger.exception("Background task error: %s", exc)
            await ctx.update_status('error', str(exc))
            self._active_jobs.pop(process_id, None)
            return

        current_status = await self._get_task_status(ctx.task_id)
        if current_status not in {'completed', 'error', 'stopped'}:
            await ctx.update_status('completed', None)
        self._active_jobs.pop(process_id, None)

    async def _update_task_status(self, task_id: int, status: str, note: Optional[str]) -> None:
        def _update() -> None:
            conn = get_db_connection()
            try:
                row = conn.execute("SELECT details FROM tasks WHERE id = ?", (task_id,)).fetchone()
                details_dict: Dict[str, Any] = {}
                if row and row['details']:
                    try:
                        details_dict = json.loads(row['details'])
                    except json.JSONDecodeError:
                        details_dict = {}
                if note is not None:
                    details_dict['last_status_note'] = note
                conn.execute(
                    "UPDATE tasks SET status = ?, details = ? WHERE id = ?",
                    (status, json.dumps(details_dict), task_id),
                )
                conn.commit()
            finally:
                conn.close()
        await asyncio.to_thread(_update)

    async def _merge_task_details(self, task_id: int, updates: Dict[str, Any]) -> None:
        def _merge() -> None:
            conn = get_db_connection()
            try:
                row = conn.execute("SELECT details FROM tasks WHERE id = ?", (task_id,)).fetchone()
                current = {}
                if row and row['details']:
                    try:
                        current = json.loads(row['details'])
                    except json.JSONDecodeError:
                        current = {}
                current.update(updates)
                conn.execute("UPDATE tasks SET details = ? WHERE id = ?", (json.dumps(current), task_id))
                conn.commit()
            finally:
                conn.close()
        await asyncio.to_thread(_merge)

    async def _get_task_status(self, task_id: int) -> str:
        def _fetch() -> str:
            conn = get_db_connection()
            try:
                row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
            finally:
                conn.close()
            return row['status'] if row else 'unknown'
        return await asyncio.to_thread(_fetch)

    async def _mark_task_error(self, task_id: int, message: str) -> None:
        def _update() -> None:
            conn = get_db_connection()
            try:
                conn.execute(
                    "UPDATE tasks SET status = 'error', details = json_set(COALESCE(details, '{}'), '$.error', ?) WHERE id = ?",
                    (message, task_id),
                )
                conn.commit()
            finally:
                conn.close()
        await asyncio.to_thread(_update)

    async def _recover_inflight_tasks(self) -> None:
        def _reset() -> int:
            conn = get_db_connection()
            try:
                rows = conn.execute(
                    "SELECT id FROM tasks WHERE status IN ('running', 'scheduled', 'interval')"
                ).fetchall()
                if not rows:
                    return 0
                conn.executemany("UPDATE tasks SET status = 'pending' WHERE id = ?", [(row['id'],) for row in rows])
                conn.commit()
                return len(rows)
            finally:
                conn.close()
        count = await asyncio.to_thread(_reset)
        if count:
            logger.warning("Mengembalikan %s tugas yang belum selesai ke status pending setelah restart.", count)

    @staticmethod
    def _parse_details(raw: Optional[str]) -> Dict[str, Any]:
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _fetch_pending_rows() -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = 'pending' ORDER BY id"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def _fetch_stop_rows() -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = 'stopped' ORDER BY id"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


async def main_async() -> None:
    service = UserbotService()
    await service.run()


if __name__ == "__main__":
    with PIDManager("userbot"):
        try:
            asyncio.run(main_async())
        except KeyboardInterrupt:
            logger.info("Layanan Userbot dihentikan secara manual.")
