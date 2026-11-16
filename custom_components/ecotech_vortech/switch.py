# SPDX-License-Identifier: GPL-2.0-only
"""Switches: pump on/off (for feeding and maintenance) and local control."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import VorTechConfigEntry
from .entity import VorTechEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: VorTechConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [PumpSwitch(coordinator, "pump")]
    advanced = coordinator.data.advanced
    if advanced is not None and advanced.local_control_enabled is not None:
        entities.append(LocalControlSwitch(coordinator, "local_control"))
    async_add_entities(entities)


class PumpSwitch(VorTechEntity, SwitchEntity):
    """Off holds the pump with its "All Off" scene; on goes back to the schedule.

    The pump ends the hold by itself after the off-hold time set in the
    options (12 hours by default), so it can't be left off by mistake.
    """

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.pump_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        remaining = data.scene_remaining_seconds
        attrs: dict[str, Any] = {"scene": data.scene_name(data.scene_id)}
        if remaining is not None:
            attrs["resumes_at"] = (dt_util.utcnow() + timedelta(seconds=remaining)).isoformat()
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_pump_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_pump_off()


class LocalControlSwitch(VorTechEntity, SwitchEntity):
    """Whether the buttons on the pump's driver can be used."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool | None:
        advanced = self.coordinator.data.advanced
        return advanced.local_control_enabled if advanced else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_advanced(local_control_enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_advanced(local_control_enabled=False)
