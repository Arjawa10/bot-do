"""Async Paperspace by DigitalOcean API client using httpx.

API base : https://api.paperspace.com/v1
Auth     : Authorization: Bearer <api_key>

Covered resources:
  - Projects : list, create, delete
  - Machines : list, get, create, start, stop, restart, delete
"""

from __future__ import annotations

from typing import Any

import httpx

from bot.utils.logger import setup_logger

logger = setup_logger("ps_client")

BASE_URL = "https://api.paperspace.com/v1"

_ERROR_MAP: dict[int, str] = {
    401: "❌ API key Paperspace tidak valid atau tidak memiliki izin.",
    403: "❌ Akses ditolak oleh Paperspace.",
    404: "❌ Resource tidak ditemukan di Paperspace.",
    429: "⏳ Rate limit Paperspace tercapai. Coba lagi nanti.",
}


class PaperspaceError(Exception):
    """Custom exception for Paperspace API errors."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class PaperspaceClient:
    """Async wrapper around the Paperspace by DigitalOcean API v1."""

    def __init__(self, token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ── Private helpers ──────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list | None:
        """Execute an HTTP request and handle errors uniformly."""
        try:
            resp = await self._client.request(
                method, path, json=json, params=params
            )
            resp.raise_for_status()
            if resp.status_code == 204:
                return None
            return resp.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in _ERROR_MAP:
                raise PaperspaceError(_ERROR_MAP[status], status) from exc
            if status == 422:
                try:
                    detail = exc.response.json().get("message", str(exc))
                except Exception:
                    detail = str(exc)
                raise PaperspaceError(
                    f"❌ Parameter tidak valid: {detail}", status
                ) from exc
            if status >= 500:
                raise PaperspaceError(
                    "❌ Server Paperspace sedang bermasalah.", status
                ) from exc
            try:
                body = exc.response.json()
                detail = body.get("message") or body.get("error") or exc.response.text
            except Exception:
                detail = exc.response.text
            raise PaperspaceError(
                f"❌ Error dari Paperspace ({status}): {detail}", status
            ) from exc
        except httpx.RequestError as exc:
            raise PaperspaceError(
                f"❌ Gagal menghubungi Paperspace: {exc}"
            ) from exc

    # ── Token validation ─────────────────────────────────────────────

    async def validate_token(self) -> bool:
        """Validate the token by listing machines. Raises PaperspaceError on failure.

        Note: GET /projects returns 500 on Paperspace side (known server bug).
        We use GET /machines instead which is known to work.
        """
        await self.list_machines()
        return True

    # ── Projects ─────────────────────────────────────────────────────

    async def list_projects(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/projects")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items", data.get("projects", []))
        return []

    async def create_project(self, name: str) -> dict[str, Any]:
        data = await self._request("POST", "/projects", json={"name": name})
        return data if isinstance(data, dict) else {}

    async def delete_project(self, project_id: str) -> None:
        await self._request("DELETE", f"/projects/{project_id}")

    # ── Machines ─────────────────────────────────────────────────────

    async def list_machines(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/machines")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items", data.get("machines", []))
        return []

    async def get_machine(self, machine_id: str) -> dict[str, Any]:
        data = await self._request("GET", f"/machines/{machine_id}")
        return data if isinstance(data, dict) else {}

    async def create_machine(
        self,
        name: str,
        machine_type: str,
        template_id: str,
        region: str,
        disk_size: int = 50,
        *,
        start_on_create: bool = True,
    ) -> dict[str, Any]:
        """Create a new Paperspace Machine.

        Args:
            name: Human-readable machine name.
            machine_type: Machine type slug, e.g. 'P4000', 'RTX4000', 'C5'.
            template_id: OS template ID (e.g. 'tlvh5xr' for Ubuntu 20.04).
            region: Region slug, e.g. 'ny2', 'ca1'.
            disk_size: Disk size in GB (default: 50).
            start_on_create: Whether to start the machine after creation.
        """
        body: dict[str, Any] = {
            "name": name,
            "machineType": machine_type,
            "templateId": template_id,
            "region": region,
            "diskSize": disk_size,
            "startOnCreate": start_on_create,
        }
        data = await self._request("POST", "/machines", json=body)
        return data if isinstance(data, dict) else {}

    async def start_machine(self, machine_id: str) -> dict[str, Any]:
        data = await self._request("PATCH", f"/machines/{machine_id}/start")
        return data if isinstance(data, dict) else {}

    async def stop_machine(self, machine_id: str) -> dict[str, Any]:
        data = await self._request("PATCH", f"/machines/{machine_id}/stop")
        return data if isinstance(data, dict) else {}

    async def restart_machine(self, machine_id: str) -> dict[str, Any]:
        data = await self._request("PATCH", f"/machines/{machine_id}/restart")
        return data if isinstance(data, dict) else {}

    async def delete_machine(self, machine_id: str) -> None:
        await self._request("DELETE", f"/machines/{machine_id}")
