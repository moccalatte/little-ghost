"""Helper utilities for Google Sheets integration."""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound

DEFAULT_CREDENTIAL_PATH = Path("credentials/service_account.json")
DEFAULT_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
ENV_CREDENTIAL_PATH = "GOOGLE_SHEETS_CREDENTIAL_FILE"


class GoogleSheetsError(RuntimeError):
    """Generic error raised for Google Sheets related failures."""


class GoogleSheetsCredentialsError(GoogleSheetsError):
    """Raised when credentials are missing or invalid."""


class GoogleSheetsPermissionError(GoogleSheetsError):
    """Raised when the service account lacks access to the spreadsheet."""


class GoogleSheetsNotFoundError(GoogleSheetsError):
    """Raised when the spreadsheet or worksheet cannot be resolved."""


class GoogleSheetsConfigError(GoogleSheetsError):
    """Raised when the provided sheet reference is not valid."""


def _resolve_credential_path(path: Path) -> Path:
    """Resolve credential file with fallbacks (env var / auto-detect)."""

    env_override = os.getenv(ENV_CREDENTIAL_PATH)
    if env_override:
        override_path = Path(env_override)
        if override_path.exists():
            return override_path
        raise GoogleSheetsCredentialsError(
            f"File kredensial dari env {ENV_CREDENTIAL_PATH} tidak ditemukan di '{override_path}'."
        )

    if path.exists():
        return path

    if path.name == "service_account.json" and path.parent.exists():
        candidates = sorted(path.parent.glob("*.json"))
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            names = ", ".join(candidate.name for candidate in candidates[:5])
            suffix = "" if len(candidates) <= 5 else ", ..."
            raise GoogleSheetsCredentialsError(
                "Beberapa file kredensial ditemukan. Harap set env GOOGLE_SHEETS_CREDENTIAL_FILE "
                f"atau ubah nama file menjadi 'service_account.json'. Ditemukan: {names}{suffix}"
            )

    raise GoogleSheetsCredentialsError(
        f"Kredensial Google Sheets tidak ditemukan di '{path}'."
    )


def _authorize_client(
    credential_path: Path | None = None,
    scopes: Sequence[str] | None = None,
) -> gspread.Client:
    path = credential_path or DEFAULT_CREDENTIAL_PATH
    if isinstance(path, str):  # pragma: no cover - defensive
        path = Path(path)

    path = _resolve_credential_path(path)

    try:
        credentials = Credentials.from_service_account_file(str(path), scopes=scopes or DEFAULT_SCOPES)
    except Exception as exc:  # pragma: no cover - depends on credential content
        raise GoogleSheetsCredentialsError("File kredensial tidak valid atau rusak.") from exc

    try:
        return gspread.authorize(credentials)
    except Exception as exc:  # pragma: no cover - jaringan
        raise GoogleSheetsError("Gagal mengotorisasi klien Google Sheets.") from exc


def _extract_gid(sheet_ref: str) -> Optional[int]:
    match = re.search(r"(?:[#?]gid=)(\d+)", sheet_ref)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:  # pragma: no cover - already digits
        return None


def _extract_key(sheet_ref: str) -> str:
    sanitized = re.split(r"[?#]", sheet_ref, maxsplit=1)[0]
    sanitized = sanitized.strip()
    if not sanitized:
        raise GoogleSheetsConfigError("Referensi Google Sheets tidak boleh kosong.")
    return sanitized


@dataclass(slots=True)
class GoogleSheetsRecorder:
    """Append-only helper bound to a specific worksheet."""

    worksheet: Any
    spreadsheet_title: str
    worksheet_title: str
    spreadsheet_id: str
    worksheet_id: int
    _lock: asyncio.Lock

    @classmethod
    async def create(
        cls,
        sheet_ref: str,
        credential_path: Path | None = None,
        scopes: Sequence[str] | None = None,
    ) -> "GoogleSheetsRecorder":
        return await asyncio.to_thread(cls._create_sync, sheet_ref, credential_path, scopes)

    @classmethod
    def _create_sync(
        cls,
        sheet_ref: str,
        credential_path: Path | None,
        scopes: Sequence[str] | None,
    ) -> "GoogleSheetsRecorder":
        if not sheet_ref:
            raise GoogleSheetsConfigError("Referensi Google Sheets belum diisi.")

        sheet_ref = sheet_ref.strip()
        client = _authorize_client(credential_path, scopes)

        gid = _extract_gid(sheet_ref)

        try:
            if sheet_ref.startswith("http://") or sheet_ref.startswith("https://"):
                spreadsheet = client.open_by_url(sheet_ref)
            else:
                key = _extract_key(sheet_ref)
                spreadsheet = client.open_by_key(key)
        except SpreadsheetNotFound as exc:
            raise GoogleSheetsNotFoundError("Spreadsheet tidak ditemukan atau tidak dapat diakses.") from exc
        except APIError as exc:
            if getattr(exc.response, "status_code", None) == 403:
                raise GoogleSheetsPermissionError(
                    "Service account tidak memiliki akses ke spreadsheet tersebut."
                ) from exc
            raise GoogleSheetsError("API Google Sheets menolak permintaan.") from exc
        except Exception as exc:  # pragma: no cover - jaringan
            raise GoogleSheetsError("Gagal membuka spreadsheet.") from exc

        worksheet = None
        try:
            if gid is not None:
                worksheet = spreadsheet.get_worksheet_by_id(gid)
            else:
                worksheet = spreadsheet.sheet1
        except WorksheetNotFound as exc:
            raise GoogleSheetsNotFoundError(
                "Worksheet dengan gid tersebut tidak ditemukan di spreadsheet."
            ) from exc
        except APIError as exc:
            raise GoogleSheetsError("Tidak dapat mengambil worksheet.") from exc
        except Exception as exc:  # pragma: no cover - jaringan
            raise GoogleSheetsError("Gagal mengambil worksheet.") from exc

        if worksheet is None:  # pragma: no cover - defensive
            raise GoogleSheetsNotFoundError("Worksheet tidak tersedia.")

        return cls(
            worksheet=worksheet,
            spreadsheet_title=getattr(spreadsheet, "title", ""),
            worksheet_title=getattr(worksheet, "title", ""),
            spreadsheet_id=getattr(spreadsheet, "id", ""),
            worksheet_id=getattr(worksheet, "id", 0),
            _lock=asyncio.Lock(),
        )

    async def append_row(self, values: Iterable[Any]) -> None:
        """Append a single row to the bound worksheet."""

        row = ["" if value is None else str(value) for value in values]

        async with self._lock:
            await asyncio.to_thread(
                self.worksheet.append_row,
                row,
                value_input_option="USER_ENTERED",
            )

    async def ensure_header(self, header: Sequence[str]) -> None:
        """Ensure the worksheet header exists, inserting if necessary."""

        async with self._lock:
            def _get_existing_first_row() -> list[list[str]]:
                return self.worksheet.get_values("1:1")

            existing = await asyncio.to_thread(_get_existing_first_row)
            if existing:
                return

            await asyncio.to_thread(
                self.worksheet.insert_row,
                list(header),
                1,
            )
