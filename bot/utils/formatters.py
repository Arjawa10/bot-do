"""Message formatting helpers for Telegram HTML messages."""

from __future__ import annotations

from typing import Any


def format_droplet_short(droplet: dict[str, Any]) -> str:
    """Format a droplet for inline keyboard button text."""
    name = droplet.get("name", "unknown")
    region = droplet.get("region", {}).get("slug", "?")
    ip = _get_ipv4(droplet)
    return f"{name} ({region}) - {ip}"


def format_droplet_list(droplets: list[dict[str, Any]]) -> str:
    """Format a list of droplets for display."""
    if not droplets:
        return "📭 <b>Tidak ada droplet aktif.</b>"

    lines: list[str] = ["📋 <b>Daftar Droplet</b>\n"]
    for d in droplets:
        status_emoji = "🟢" if d.get("status") == "active" else "🔴"
        name = d.get("name", "unknown")
        droplet_id = d.get("id", "?")
        status = d.get("status", "?")
        region = d.get("region", {}).get("slug", "?")
        vcpus = d.get("vcpus", "?")
        memory = d.get("memory", 0)
        memory_gb = f"{memory / 1024:.0f}" if isinstance(memory, (int, float)) and memory >= 1024 else f"{memory}"
        ip = _get_ipv4(d)
        lines.append(
            f"{status_emoji} <b>{name}</b>\n"
            f"   ID: <code>{droplet_id}</code>\n"
            f"   Status: {status}\n"
            f"   Region: {region}\n"
            f"   Size: {vcpus} vCPU / {memory_gb} GB RAM\n"
            f"   IP: <code>{ip}</code>\n"
        )
    return "\n".join(lines)


def format_droplet_detail(d: dict[str, Any]) -> str:
    """Format detailed droplet info."""
    status_emoji = "🟢" if d.get("status") == "active" else "🔴"
    name = d.get("name", "unknown")
    droplet_id = d.get("id", "?")
    status = d.get("status", "?")
    region = d.get("region", {})
    size = d.get("size", {})
    image = d.get("image", {})
    ip4 = _get_ipv4(d)
    ip6 = _get_ipv6(d)
    memory = size.get("memory", 0)
    memory_gb = f"{memory / 1024:.0f}" if isinstance(memory, (int, float)) and memory >= 1024 else f"{memory}"
    disk = size.get("disk", "?")
    created = d.get("created_at", "?")
    tags = ", ".join(d.get("tags", [])) or "—"

    return (
        f"{status_emoji} <b>Detail Droplet</b>\n\n"
        f"📛 Nama: <b>{name}</b>\n"
        f"🆔 ID: <code>{droplet_id}</code>\n"
        f"📊 Status: {status}\n"
        f"🌍 Region: {region.get('name', '?')} (<code>{region.get('slug', '?')}</code>)\n"
        f"💻 Size: {size.get('vcpus', '?')} vCPU / {memory_gb} GB RAM / {disk} GB Disk\n"
        f"💵 Harga: ${size.get('price_monthly', '?')}/bulan\n"
        f"🖼️ Image: {image.get('distribution', '?')} {image.get('name', '?')}\n"
        f"🌐 IPv4: <code>{ip4}</code>\n"
        f"🌐 IPv6: <code>{ip6}</code>\n"
        f"🏷️ Tags: {tags}\n"
        f"📅 Dibuat: {created}\n"
    )


def format_droplet_created(d: dict[str, Any]) -> str:
    """Format newly created droplet info."""
    name = d.get("name", "unknown")
    droplet_id = d.get("id", "?")
    status = d.get("status", "?")
    region = d.get("region", {}).get("slug", "?")
    size_slug = d.get("size_slug", "?")
    ip = _get_ipv4(d)

    return (
        f"✅ <b>Droplet berhasil dibuat!</b>\n\n"
        f"📛 Nama: <b>{name}</b>\n"
        f"🆔 ID: <code>{droplet_id}</code>\n"
        f"📊 Status: {status}\n"
        f"🌍 Region: {region}\n"
        f"💻 Size: {size_slug}\n"
        f"🌐 IP: <code>{ip}</code>\n\n"
        f"⏳ Droplet sedang dalam proses provisioning. "
        f"Gunakan /info untuk cek status terbaru."
    )


def _get_ipv4(droplet: dict[str, Any]) -> str:
    """Extract the public IPv4 address from a droplet dict."""
    networks = droplet.get("networks", {})
    for net in networks.get("v4", []):
        if net.get("type") == "public":
            return net.get("ip_address", "N/A")
    return "N/A"


def _get_ipv6(droplet: dict[str, Any]) -> str:
    """Extract the public IPv6 address from a droplet dict."""
    networks = droplet.get("networks", {})
    for net in networks.get("v6", []):
        if net.get("type") == "public":
            return net.get("ip_address", "N/A")
    return "N/A"
