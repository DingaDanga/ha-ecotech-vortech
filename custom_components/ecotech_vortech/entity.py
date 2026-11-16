# SPDX-License-Identifier: GPL-2.0-only
"""Base entity for a VorTech pump."""

from __future__ import annotations

from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MODEL, CONF_SERIAL, DOMAIN, MANUFACTURER
from .coordinator import VorTechCoordinator


class VorTechEntity(CoordinatorEntity[VorTechCoordinator]):
    """An entity of one pump; everything lives on one device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VorTechCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        serial = entry.data[CONF_SERIAL]
        self._attr_unique_id = f"{serial}_{key}"
        description = getattr(self, "entity_description", None)
        if description is None or description.translation_key is None:
            self._attr_translation_key = key
        data = coordinator.data
        info = data.info if data else {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            connections={(CONNECTION_BLUETOOTH, entry.data[CONF_ADDRESS])},
            manufacturer=info.get("manufacturer") or MANUFACTURER,
            model=entry.data.get(CONF_MODEL) or info.get("model"),
            model_id=info.get("model"),
            name=(info.get("name") or entry.title).strip(),
            serial_number=serial,
            sw_version=data.main_firmware if data else None,
            hw_version=_hardware_revision(data.poll.metadata.hardware_info) if data else None,
        )


def _hardware_revision(hardware_info: dict | None) -> str | None:
    if not hardware_info:
        return None
    for key, value in hardware_info.items():
        if getattr(key, "name", str(key)) == "Revision":
            return str(value)
    return None
