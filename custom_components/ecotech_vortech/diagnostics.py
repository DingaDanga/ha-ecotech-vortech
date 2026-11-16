# SPDX-License-Identifier: GPL-2.0-only
"""Diagnostics download: everything read from the pump, with identifiers removed."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from mobius import pump_schedule_to_dict

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import VorTechConfigEntry

TO_REDACT = {"address", "serial", "mac_address", "serial_number", "unique_id", "title"}


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, bytes):
        return value.hex()
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {str(_plain(k)): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    return value


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: VorTechConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    poll = data.poll if data else None
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "link": {
                "state": coordinator.link_state,
                "address": coordinator.link.address,
                "connections_made": coordinator.link.connect_count,
                "last_error": coordinator.link.last_error,
                "rssi": coordinator.rssi,
            },
            "statistics": dict(coordinator.stats),
            "device_info": _plain(poll.device_info) if poll else None,
            "telemetry": _plain(poll.pump_telemetry) if poll else None,
            "operation_state": _plain(poll.operation_state) if poll else None,
            "schedule": pump_schedule_to_dict(data.schedule) if data else None,
            "scenes": _plain(poll.configured_scenes) if poll else None,
            "current_scene": _plain(poll.current_scene) if poll else None,
            "battery_backup": _plain(poll.battery_backup) if poll else None,
            "metadata": _plain(poll.metadata) if poll else None,
            "vectra_info": _plain(poll.vectra_info) if poll else None,
            "extra_values": _plain(data.extra_values) if data else None,
            "firmware_latest": coordinator.firmware_latest,
        },
        TO_REDACT,
    )
