# SPDX-License-Identifier: GPL-2.0-only
"""Freeing a Bluetooth proxy that is still holding a dead connection to the pump.

The pump accepts one Bluetooth connection and stops advertising while it has
one. When a link drops, an ESPHome Bluetooth proxy can keep its end open: the
pump then stays silent and Home Assistant cannot find it again. This module
finds the proxy that last carried the connection and makes it let go, first by
asking it to disconnect the pump, then (only when Home Assistant's own records
show the proxy still holding the pump) by reloading the proxy.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

_LOGGER = logging.getLogger(__name__)

ESPHOME_DOMAIN = "esphome"
DISCONNECT_TIMEOUT = 10.0


def _proxy_entries_for_source(hass: HomeAssistant, source: str) -> list[ConfigEntry]:
    """ESPHome config entries behind the Bluetooth scanner `source`."""
    registry = dr.async_get(hass)
    device = registry.async_get_device(connections={(dr.CONNECTION_BLUETOOTH, source.upper())})
    if device is None:
        device = registry.async_get_device(connections={(dr.CONNECTION_BLUETOOTH, source.lower())})
    if device is None:
        return []
    entry_ids: set[str] = set(device.config_entries)
    if device.via_device_id:
        parent = registry.async_get(device.via_device_id)
        if parent is not None:
            entry_ids.update(parent.config_entries)
    entries = []
    for entry_id in entry_ids:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == ESPHOME_DOMAIN:
            entries.append(entry)
    return entries


def _remote_sources(hass: HomeAssistant) -> list[str]:
    """Sources of every scanner Home Assistant currently has."""
    current = getattr(bluetooth, "async_current_scanners", None)
    if current is None:
        return []
    try:
        return [scanner.source for scanner in current(hass)]
    except Exception:  # noqa: BLE001
        return []


def proxies(hass: HomeAssistant, preferred_source: str | None) -> list[tuple[str, ConfigEntry]]:
    """(scanner source, ESPHome entry) pairs, the last used proxy first."""
    sources: list[str] = []
    if preferred_source:
        sources.append(preferred_source)
    for source in _remote_sources(hass):
        if source not in sources:
            sources.append(source)
    found: list[tuple[str, ConfigEntry]] = []
    seen: set[str] = set()
    for source in sources:
        for entry in _proxy_entries_for_source(hass, source):
            if entry.entry_id not in seen:
                seen.add(entry.entry_id)
                found.append((source, entry))
    return found


def holds_address(source: str, address: str) -> bool | None:
    """Whether Home Assistant's Bluetooth records show the scanner `source`
    holding a connection to `address`. None when that can't be read."""
    try:
        from habluetooth import get_manager  # noqa: PLC0415

        allocations = get_manager().async_current_allocations(source)
    except Exception:  # noqa: BLE001
        return None
    if not allocations:
        return None
    wanted = address.upper()
    for allocation in allocations:
        allocated = [str(item).upper() for item in getattr(allocation, "allocated", [])]
        if wanted in allocated:
            return True
        slots = getattr(allocation, "slots", None)
        free = getattr(allocation, "free", None)
        if not allocated and slots is not None and free is not None and free < slots:
            # A slot is in use that Home Assistant has no owner for.
            return True
    return False


def _client(entry: ConfigEntry) -> Any | None:
    runtime = getattr(entry, "runtime_data", None)
    return getattr(runtime, "client", None)


def can_disconnect(entry: ConfigEntry) -> bool:
    return hasattr(_client(entry), "bluetooth_device_disconnect")


async def ask_disconnect(entry: ConfigEntry, address: str) -> bool:
    """Asks the proxy to drop its connection to `address`."""
    client = _client(entry)
    if client is None or not hasattr(client, "bluetooth_device_disconnect"):
        return False
    try:
        async with asyncio.timeout(DISCONNECT_TIMEOUT + 2):
            await client.bluetooth_device_disconnect(int(address.replace(":", ""), 16))
    except Exception as err:  # noqa: BLE001 - "not connected" also lands here
        _LOGGER.debug("Proxy %s: disconnect of %s answered %r", entry.title, address, err)
        return False
    return True


async def reload_proxy(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.state is not ConfigEntryState.LOADED:
        return False
    try:
        return await hass.config_entries.async_reload(entry.entry_id)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Proxy %s: reload failed", entry.title, exc_info=True)
        return False


def describe(hass: HomeAssistant, preferred_source: str | None, address: str) -> list[dict]:
    """For diagnostics: what the freeing logic can see right now."""
    return [
        {
            "source": source,
            "proxy": entry.title,
            "can_disconnect": can_disconnect(entry),
            "holds_pump": holds_address(source, address),
        }
        for source, entry in proxies(hass, preferred_source)
    ]
