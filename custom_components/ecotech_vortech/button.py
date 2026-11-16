# SPDX-License-Identifier: GPL-2.0-only
"""Buttons: feed, back to schedule, Mobius app hand-over and maintenance."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VorTechConfigEntry
from .coordinator import VorTechCoordinator
from .entity import VorTechEntity


@dataclass(frozen=True, kw_only=True)
class VorTechButtonDescription(ButtonEntityDescription):
    press: Callable[[VorTechCoordinator], Awaitable[None]]


BUTTONS: tuple[VorTechButtonDescription, ...] = (
    VorTechButtonDescription(key="feed", translation_key="feed", press=lambda c: c.async_feed()),
    VorTechButtonDescription(
        key="resume_schedule", translation_key="resume_schedule", press=lambda c: c.async_resume_schedule()
    ),
    VorTechButtonDescription(
        key="release_for_app", translation_key="release_for_app", press=lambda c: c.async_release_for_app()
    ),
    VorTechButtonDescription(key="reconnect", translation_key="reconnect", press=lambda c: c.async_reconnect()),
    VorTechButtonDescription(
        key="sync_time",
        translation_key="sync_time",
        entity_category=EntityCategory.CONFIG,
        press=lambda c: c.async_sync_time(),
    ),
    VorTechButtonDescription(
        key="reboot",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        press=lambda c: c.async_reboot(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: VorTechConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(VorTechButton(coordinator, description) for description in BUTTONS)


class VorTechButton(VorTechEntity, ButtonEntity):
    entity_description: VorTechButtonDescription

    def __init__(self, coordinator: VorTechCoordinator, description: VorTechButtonDescription) -> None:
        self.entity_description = description
        super().__init__(coordinator, description.key)
        if description.device_class is not None and description.translation_key is None:
            self._attr_translation_key = None

    async def async_press(self) -> None:
        await self.entity_description.press(self.coordinator)
