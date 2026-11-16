# SPDX-License-Identifier: GPL-2.0-only
"""Firmware: shows whether EcoTech has newer pump firmware.

The check asks EcoTech's firmware server the same question the Mobius app
asks (no login). Installing is done in the Mobius app.
"""

from __future__ import annotations

from homeassistant.components.update import UpdateEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VorTechConfigEntry
from .const import CONF_FIRMWARE_CHECK, DEFAULT_FIRMWARE_CHECK
from .entity import VorTechEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: VorTechConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if coordinator.option(CONF_FIRMWARE_CHECK, DEFAULT_FIRMWARE_CHECK):
        async_add_entities([FirmwareUpdate(coordinator, "firmware_update")])


class FirmwareUpdate(VorTechEntity, UpdateEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_release_summary = "Install new pump firmware from the Mobius app."

    def _images(self) -> dict[str, str]:
        return {
            image.firmware_type.name: image.version
            for image in self.coordinator.data.poll.metadata.firmware_images or []
        }

    @property
    def installed_version(self) -> str | None:
        images = self._images()
        return " / ".join(images.values()) if images else self.coordinator.data.main_firmware

    @property
    def latest_version(self) -> str | None:
        images = self._images()
        latest = self.coordinator.firmware_latest
        if not latest:
            return self.installed_version
        return " / ".join(latest.get(name, version) for name, version in images.items())

    @property
    def release_url(self) -> str | None:
        return self.coordinator.firmware_release_url
