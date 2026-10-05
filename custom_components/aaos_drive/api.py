"""Google Drive API reads only. OAuth token refresh belongs to Home Assistant."""

from __future__ import annotations

import re
from typing import Awaitable, Callable

import aiohttp

from .const import API_ROOT, FOLDER_MIME, MAX_FILE_BYTES
from .model import InvalidExport


class DriveError(Exception):
    """A transient Drive read failed."""


class DriveAuthError(DriveError):
    """The Drive grant needs renewed consent."""


def folder_id(value: str) -> str:
    value = value.strip()
    match = re.fullmatch(r"https://drive\.google\.com/drive/(?:u/\d+/)?folders/([\w-]+)(?:\?.*)?", value)
    result = match[1] if match else value
    if not re.fullmatch(r"[A-Za-z0-9_-]+", result):
        raise InvalidExport("Enter a Google Drive folder ID or folder URL")
    return result


class ReadOnlyDrive:
    def __init__(self, session: aiohttp.ClientSession, token: Callable[[], Awaitable[str]]):
        self.session = session
        self.token = token

    async def _read(self, path: str, params: dict, limit: int, media: bool = False):
        access_token = await self.token()
        async with self.session.get(
            f"{API_ROOT}/{path}", params=params,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=aiohttp.ClientTimeout(total=180), allow_redirects=False,
        ) as response:
            if response.status == 401:
                raise DriveAuthError("Google Drive authorization expired")
            if response.status == 403:
                # Quota exhaustion is transient; insufficient grants require reauth.
                try:
                    error = await response.json()
                    reasons = {e.get("reason") for e in error.get("error", {}).get("errors", [])}
                except (ValueError, aiohttp.ClientError):
                    reasons = set()
                if reasons & {"insufficientPermissions", "authError"}:
                    raise DriveAuthError("Google Drive read-only permission is required")
                raise DriveError("Google Drive denied the read (permission, API configuration or quota)")
            if response.status >= 300:
                raise DriveError(f"Google Drive read failed with HTTP {response.status}")
            data = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                data.extend(chunk)
                if len(data) > limit:
                    raise InvalidExport("Drive response exceeds the import limit")
            if media:
                return bytes(data)
            from .model import json_object
            return json_object(bytes(data))

    async def metadata(self, file_id: str) -> dict:
        return await self._read(f"files/{folder_id(file_id)}", {
            "fields": "id,name,mimeType,size,sha256Checksum,trashed", "supportsAllDrives": "true",
        }, 1024 * 1024)

    async def children(self, parent: str) -> list[dict]:
        parent = folder_id(parent)
        result, page_token = [], None
        while True:
            params = {
                "q": f"'{parent}' in parents and trashed = false", "spaces": "drive",
                "fields": "nextPageToken,incompleteSearch,files(id,name,mimeType,size,sha256Checksum)",
                "pageSize": "1000", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token
            page = await self._read("files", params, 8 * 1024 * 1024)
            if page.get("incompleteSearch"):
                raise DriveError("Drive returned an incomplete folder listing; retry later")
            result.extend(page.get("files", []))
            page_token = page.get("nextPageToken")
            if not page_token:
                return result

    async def child_folder(self, parent: str, name: str) -> str:
        matches = [f for f in await self.children(parent) if f.get("name") == name and f.get("mimeType") == FOLDER_MIME]
        if len(matches) != 1:
            raise InvalidExport(f"Expected one {name} folder; sync AAOS Logging V3 first")
        return matches[0]["id"]

    async def download(self, file_id: str, limit: int = MAX_FILE_BYTES) -> bytes:
        return await self._read(f"files/{folder_id(file_id)}", {
            "alt": "media", "supportsAllDrives": "true",
        }, limit, media=True)
