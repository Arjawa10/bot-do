"""Async Paperspace by DigitalOcean API client using httpx.

API base: https://api.paperspace.com/v1
Auth:     Authorization: Bearer <api_key>

Covered resources:
  - Projects   : list, create, delete
  - Notebooks  : list, create, stop, delete
  - Machines   : list, get (read-only)
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

    # ── Helper to validate token ──────────────────────────────────────

    async def validate_token(self) -> bool:
        """Validate the token by listing projects. Raises PaperspaceError on failure."""
        await self.list_projects()
        return True

    # ── Projects ─────────────────────────────────────────────────────

    async def list_projects(self) -> list[dict[str, Any]]:
        """List all Paperspace projects for the authenticated team."""
        data = await self._request("GET", "/projects")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items", data.get("projects", []))
        return []

    async def get_project(self, project_id: str) -> dict[str, Any]:
        """Get a specific project by ID."""
        data = await self._request("GET", f"/projects/{project_id}")
        return data if isinstance(data, dict) else {}

    async def create_project(self, name: str) -> dict[str, Any]:
        """Create a new project with the given name."""
        data = await self._request("POST", "/projects", json={"name": name})
        return data if isinstance(data, dict) else {}

    async def delete_project(self, project_id: str) -> None:
        """Delete a project by ID."""
        await self._request("DELETE", f"/projects/{project_id}")

    # ── Notebooks ────────────────────────────────────────────────────

    async def list_notebooks(
        self, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List all notebooks, optionally filtered by project ID."""
        params: dict[str, Any] = {}
        if project_id:
            params["projectId"] = project_id
        data = await self._request("GET", "/notebooks", params=params or None)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items", data.get("notebooks", []))
        return []

    async def get_notebook(self, notebook_id: str) -> dict[str, Any]:
        """Get a specific notebook by ID."""
        data = await self._request("GET", f"/notebooks/{notebook_id}")
        return data if isinstance(data, dict) else {}

    async def create_notebook(
        self,
        project_id: str,
        machine_type: str,
        name: str,
        *,
        container: str = "paperspace/nb-pytorch:latest",
        auto_shutdown_timeout: int = 1,
    ) -> dict[str, Any]:
        """Create and start a new notebook.

        Args:
            project_id: ID of the parent project.
            machine_type: Machine type slug, e.g. 'P4000', 'P5000', 'C5'.
            name: Human-readable notebook name.
            container: Docker image for the notebook (default: PyTorch).
            auto_shutdown_timeout: Hours of inactivity before auto-shutdown.
        """
        body: dict[str, Any] = {
            "projectId": project_id,
            "machineType": machine_type,
            "name": name,
            "container": container,
            "autoShutdownTimeout": auto_shutdown_timeout,
        }
        data = await self._request("POST", "/notebooks", json=body)
        return data if isinstance(data, dict) else {}

    async def stop_notebook(self, notebook_id: str) -> dict[str, Any]:
        """Stop a running notebook."""
        data = await self._request("POST", f"/notebooks/{notebook_id}/stop")
        return data if isinstance(data, dict) else {}

    async def delete_notebook(self, notebook_id: str) -> None:
        """Delete a notebook by ID."""
        await self._request("DELETE", f"/notebooks/{notebook_id}")

    # ── Machines (read-only) ─────────────────────────────────────────

    async def list_machines(self) -> list[dict[str, Any]]:
        """List all Paperspace machines for the authenticated team."""
        data = await self._request("GET", "/machines")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items", data.get("machines", []))
        return []

    async def get_machine(self, machine_id: str) -> dict[str, Any]:
        """Get details of a specific machine."""
        data = await self._request("GET", f"/machines/{machine_id}")
        return data if isinstance(data, dict) else {}
