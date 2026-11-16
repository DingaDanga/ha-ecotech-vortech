# SPDX-License-Identifier: GPL-2.0-only
"""Numbers: speed, feed time and battery backup speed."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VorTechConfigEntry
from .const import MAX_SCENE_MINUTES, SPEED_MAX_PERCENT, SPEED_MIN_PERCENT
from .entity import VorTechEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: VorTechConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[NumberEntity] = [SpeedNumber(coordinator, "speed"), FeedTimeNumber(coordinator, "feed_time")]
    if coordinator.data.poll.battery_backup is not None:
        entities.append(BatteryBackupNumber(coordinator, "battery_backup_speed"))
    async_add_entities(entities)


class SpeedNumber(VorTechEntity, NumberEntity):
    """The speed of the schedule block running now (the app's speed slider).

    The wave mode and every other block of the schedule are kept as they are.
    """

    _attr_native_min_value = SPEED_MIN_PERCENT
    _attr_native_max_value = SPEED_MAX_PERCENT
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.schedule_speed_percent

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_speed(value)


class FeedTimeNumber(VorTechEntity, NumberEntity):
    """How long the Feed button pauses the pump."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 1
    _attr_native_max_value = 60
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float:
        return self.coordinator.feed_minutes

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_feed_minutes(min(value, MAX_SCENE_MINUTES))


class BatteryBackupNumber(VorTechEntity, NumberEntity):
    """Speed the pump runs at on its battery backup."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 1

    @property
    def native_max_value(self) -> float:
        return self.coordinator.data.battery_backup_max_percent or 100

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.battery_backup_percent

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_battery_backup(value)
