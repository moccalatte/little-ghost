"""Shared helpers for wizard command implementations."""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Iterable, List, Sequence, Tuple

from core.infra.database import get_db_connection


def fetch_userbot_groups(userbot_id: int, group_type: str | None = None) -> Sequence[sqlite3.Row]:
    conn = get_db_connection()
    try:
        base_query = "SELECT telegram_group_id, group_name, group_type, username FROM groups WHERE userbot_id = ?"
        params: list = [userbot_id]
        if group_type:
            base_query += " AND group_type = ?"
            params.append(group_type)
        base_query += " ORDER BY group_name"
        return conn.execute(base_query, params).fetchall()
    finally:
        conn.close()


def get_group_stats(userbot_id: int) -> Tuple[int, int]:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT "
            "SUM(CASE WHEN group_type = 'group' THEN 1 ELSE 0 END) AS groups_count,"
            "SUM(CASE WHEN group_type = 'channel' THEN 1 ELSE 0 END) AS channels_count"
            " FROM groups WHERE userbot_id = ?",
            (userbot_id,),
        ).fetchone()
        return (row["groups_count"] or 0, row["channels_count"] or 0) if row else (0, 0)
    finally:
        conn.close()


def fetch_userbot_tasks(userbot_id: int) -> Sequence[sqlite3.Row]:
    conn = get_db_connection()
    try:
        return conn.execute(
            "SELECT id, process_id, command, status, start_time, details FROM tasks WHERE userbot_id = ? ORDER BY id DESC",
            (userbot_id,),
        ).fetchall()
    finally:
        conn.close()


def create_task(
    userbot_id: int,
    command: str,
    details: dict,
    status: str = "pending",
) -> tuple[str, int]:
    process_id = str(uuid.uuid4())
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tasks (userbot_id, process_id, command, status, details) VALUES (?, ?, ?, ?, ?)",
            (userbot_id, process_id, command, status, json.dumps(details)),
        )
        conn.commit()
        return process_id, cursor.lastrowid
    finally:
        conn.close()


def parse_selection_indexes(text: str, max_index: int) -> List[int]:
    """Convert comma-separated selection indexes (1-based) into a list of ints."""
    indexes: List[int] = []
    for chunk in text.replace(" ", "").split(","):
        if not chunk:
            continue
        if not chunk.isdigit():
            raise ValueError(f"'{chunk}' bukan angka yang valid.")
        value = int(chunk)
        if value < 1 or value > max_index:
            raise ValueError(f"Pilihan {value} berada di luar rentang 1-{max_index}.")
        indexes.append(value)
    if not indexes:
        raise ValueError("Tidak ada pilihan yang ditemukan.")
    return indexes


def safe_json_loads(value: str | None) -> dict:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def mark_tasks_stopped(userbot_id: int, process_ids: Iterable[str]) -> None:
    ids = list(process_ids)
    if not ids:
        return
    conn = get_db_connection()
    try:
        conn.executemany(
            "UPDATE tasks SET status = 'stopped' WHERE userbot_id = ? AND process_id = ?",
            [(userbot_id, pid) for pid in ids],
        )
        conn.commit()
    finally:
        conn.close()


def parse_custom_target_ids(raw: str) -> List[int]:
    """Parse custom chat IDs (without -100 prefix) into Telegram numeric IDs."""
    targets: List[int] = []
    if not raw:
        raise ValueError("Masukkan minimal satu ID chat.")
    for chunk in raw.replace(" ", "").split(","):
        if not chunk:
            continue
        if chunk.startswith("-100"):
            value = chunk
        elif chunk.startswith("-"):
            value = chunk
        else:
            value = f"-100{chunk}"
        try:
            targets.append(int(value))
        except ValueError as exc:  # pragma: no cover - input sanitizing
            raise ValueError(f"ID chat '{chunk}' tidak valid.") from exc
    if not targets:
        raise ValueError("Tidak ada ID chat yang valid.")
    return targets
