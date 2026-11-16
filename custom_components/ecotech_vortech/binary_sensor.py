# SPDX-License-Identifier: GPL-2.0-only
"""Binary sensors: fault, feeding, battery backup and Bluetooth link."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VorTechConfigEntry
from .coordinator import VorTechCoordinator
from .entity import VorTechEntity


@dataclass(frozen=True, kw_only=True)
class VorTechBinaryDescription(BinarySensorEntityDescription):
    value: Callable[[VorTechCoordinator], bool | None]


BINARY_SENSORS: tuple[VorTechBinaryDescription, ...] = (
    VorTechBinaryDescription(
        key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value=lambda c: (c.data.error_state or "NoError") != "NoError",
    ),
    VorTechBinaryDescription(
        key="feeding",
        translation_key="feeding",
        value=lambda c: c.data.feeding,
    ),
    VorTechBinaryDescription(
        key="on_battery",
        translation_key="on_battery",
        value=lambda c: c.data.operation_mode == "BatteryBackup",
    ),
    VorTechBinaryDescription(
        key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda c: c.link.is_connected,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: VorTechConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(VorTechBinarySensor(coordinator, d) for d in BINARY_SENSORS)


class VorTechBinarySensor(VorTechEntity, BinarySensorEntity):
    entity_description: VorTechBinaryDescription

    def __init__(self, coordinator: VorTechCoordinator, description: VorTechBinaryDescription) -> None:
        self.entity_description = description
        super().__init__(coordinator, description.key)
        if description.device_class is not None and description.translation_key is None:
            self._attr_translation_key = None

    @property
    def available(self) -> bool:
        # The link state is worth showing even when readings fail.
        if self.entity_description.key == "connected":
            return self.coordinator.data is not None
        return super().available

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self.coordinator)
