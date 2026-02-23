"""Async DigitalOcean API v2 client using httpx."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from bot.utils.logger import setup_logger

logger = setup_logger("do_client")

BASE_URL = "https://api.digitalocean.com/v2"

# Map HTTP status codes to user-friendly error messages
_ERROR_MAP: dict[int, str] = {
    401: "❌ Token DigitalOcean tidak valid.",
    404: "❌ Droplet tidak ditemukan.",
    429: "⏳ Rate limit tercapai. Coba lagi nanti.",
}


class DigitalOceanError(Exception):
    """Custom exception for DO API errors."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class DigitalOceanClient:
    """Async wrapper around the DigitalOcean API v2."""

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
    ) -> dict[str, Any] | None:
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
            # Try known error map first
            if status in _ERROR_MAP:
                raise DigitalOceanError(_ERROR_MAP[status], status) from exc
            # 422 – validation
            if status == 422:
                detail = exc.response.json().get("message", str(exc))
                raise DigitalOceanError(
                    f"❌ Parameter tidak valid: {detail}", status
                ) from exc
            # 5xx
            if status >= 500:
                raise DigitalOceanError(
                    "❌ Server DigitalOcean sedang bermasalah.", status
                ) from exc
            raise DigitalOceanError(
                f"❌ Error dari DigitalOcean: {exc.response.text}", status
            ) from exc
        except httpx.RequestError as exc:
            raise DigitalOceanError(
                f"❌ Gagal menghubungi DigitalOcean: {exc}"
            ) from exc

    # ── Droplets ─────────────────────────────────────────────────────

    async def list_droplets(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/droplets", params={"per_page": 200})
        return (data or {}).get("droplets", [])

    async def get_droplet(self, droplet_id: int) -> dict[str, Any]:
        data = await self._request("GET", f"/droplets/{droplet_id}")
        return (data or {}).get("droplet", {})

    async def create_droplet(
        self,
        name: str,
        region: str,
        size: str,
        image: str,
        ssh_keys: list[str | int] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name,
            "region": region,
            "size": size,
            "image": image,
            "ipv6": True,
            "monitoring": True,
            "tags": ["telegram-bot"],
        }
        if ssh_keys:
            body["ssh_keys"] = ssh_keys
        data = await self._request("POST", "/droplets", json=body)
        return (data or {}).get("droplet", {})

    async def destroy_droplet(self, droplet_id: int) -> None:
        await self._request("DELETE", f"/droplets/{droplet_id}")

    # ── Droplet Actions ──────────────────────────────────────────────

    async def _droplet_action(
        self, droplet_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        data = await self._request(
            "POST", f"/droplets/{droplet_id}/actions", json=payload
        )
        return (data or {}).get("action", {})

    async def power_on_droplet(self, droplet_id: int) -> dict[str, Any]:
        return await self._droplet_action(droplet_id, {"type": "power_on"})

    async def power_off_droplet(self, droplet_id: int) -> dict[str, Any]:
        return await self._droplet_action(droplet_id, {"type": "power_off"})

    async def reboot_droplet(self, droplet_id: int) -> dict[str, Any]:
        return await self._droplet_action(droplet_id, {"type": "reboot"})

    async def resize_droplet(
        self, droplet_id: int, size: str, disk: bool = True
    ) -> dict[str, Any]:
        return await self._droplet_action(
            droplet_id, {"type": "resize", "disk": disk, "size": size}
        )

    # ── Actions ──────────────────────────────────────────────────────

    async def get_action(self, action_id: int) -> dict[str, Any]:
        data = await self._request("GET", f"/actions/{action_id}")
        return (data or {}).get("action", {})

    async def poll_action(
        self, action_id: int, interval: int = 5, timeout: int = 120
    ) -> dict[str, Any]:
        """Poll an action until it completes or times out."""
        elapsed = 0
        while elapsed < timeout:
            action = await self.get_action(action_id)
            status = action.get("status")
            if status == "completed":
                return action
            if status == "errored":
                raise DigitalOceanError("❌ Action gagal (errored).")
            await asyncio.sleep(interval)
            elapsed += interval
        raise DigitalOceanError("⏳ Timeout menunggu action selesai.")

    # ── Metadata ─────────────────────────────────────────────────────

    async def list_regions(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/regions", params={"per_page": 200})
        regions = (data or {}).get("regions", [])
        return [r for r in regions if r.get("available")]

    async def list_sizes(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/sizes", params={"per_page": 200})
        sizes = (data or {}).get("sizes", [])
        return [s for s in sizes if s.get("available")]

    async def list_images(
        self, image_type: str = "distribution"
    ) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", "/images", params={"type": image_type, "per_page": 200}
        )
        return (data or {}).get("images", [])
