# SPDX-License-Identifier: GPL-2.0-only
"""Selects: wave mode, scene and status-light dimming."""

from __future__ import annotations

from mobius import PumpMode

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VorTechConfigEntry
from .entity import VorTechEntity

SCHEDULE_OPTION = "Schedule"

# The app's choices for how long until the status light dims (seconds).
AUTO_DIM_OPTIONS = {
    "always_on": 0,
    "30_seconds": 30,
    "1_minute": 60,
    "5_minutes": 300,
    "10_minutes": 600,
    "30_minutes": 1800,
    "1_hour": 3600,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: VorTechConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = [WaveModeSelect(coordinator, "wave_mode"), SceneSelect(coordinator, "scene")]
    advanced = coordinator.data.advanced
    if advanced is not None and advanced.auto_dim_timeout is not None:
        entities.append(AutoDimSelect(coordinator, "led_auto_dim"))
    async_add_entities(entities)


def _mode_key(mode: PumpMode) -> str:
    return mode.name.lower()


class WaveModeSelect(VorTechEntity, SelectEntity):
    """Wave mode of the schedule block running now. Its speed is kept."""

    @property
    def options(self) -> list[str]:
        keys = [_mode_key(m) for m in self.coordinator.supported_modes()]
        current = self.current_option
        if current and current not in keys:
            keys.append(current)
        return keys

    @property
    def current_option(self) -> str | None:
        point = self.coordinator.data.active_point
        return _mode_key(point.pump.mode) if point else None

    async def async_select_option(self, option: str) -> None:
        mode = next(m for m in PumpMode if _mode_key(m) == option)
        await self.coordinator.async_set_mode(mode)


class SceneSelect(VorTechEntity, SelectEntity):
    """Run one of the pump's scenes (as set up in the Mobius app), or go
    back to the schedule."""

    _attr_translation_key = "scene"

    @property
    def options(self) -> list[str]:
        names = [SCHEDULE_OPTION] + [s.name for s in self.coordinator.data.scenes if s.name]
        current = self.current_option
        if current not in names:
            names.append(current)
        return names

    @property
    def current_option(self) -> str:
        data = self.coordinator.data
        return data.scene_name(data.scene_id) or SCHEDULE_OPTION

    async def async_select_option(self, option: str) -> None:
        if option == SCHEDULE_OPTION:
            await self.coordinator.async_resume_schedule()
            return
        scene = next((s for s in self.coordinator.data.scenes if s.name == option), None)
        if scene is None:
            return
        await self.coordinator.async_start_scene(scene.id)


class AutoDimSelect(VorTechEntity, SelectEntity):
    """How long until the status light on the driver dims."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(AUTO_DIM_OPTIONS)

    @property
    def current_option(self) -> str | None:
        advanced = self.coordinator.data.advanced
        if advanced is None or advanced.auto_dim_timeout is None:
            return None
        value = advanced.auto_dim_timeout
        return next((k for k, v in AUTO_DIM_OPTIONS.items() if v == value), None)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_advanced(auto_dim_timeout=AUTO_DIM_OPTIONS[option])
