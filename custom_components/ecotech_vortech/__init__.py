# SPDX-License-Identifier: GPL-2.0-only
"""EcoTech VorTech pumps over Bluetooth (Mobius protocol).

Connects to the pump itself, through Home Assistant's Bluetooth (a local
adapter or an ESPHome Bluetooth proxy), using the python-mobius library.
"""

from __future__ import annotations

import logging

from mobius import parse_advertisement

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_SERIAL, DOMAIN, MOBIUS_COMPANY_ID
from .coordinator import VorTechCoordinator
from .pump import PumpLink
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type VorTechConfigEntry = ConfigEntry[VorTechCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions once."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: VorTechConfigEntry) -> bool:
    """Set up one pump."""
    serial: str = entry.data[CONF_SERIAL]
    link = PumpLink(hass, entry.data[CONF_ADDRESS], entry.title)
    coordinator = VorTechCoordinator(hass, entry, link)
    await coordinator.async_load()

    @callback
    def _update_rssi(service_info: bluetooth.BluetoothServiceInfoBleak) -> None:
        # Several adapters/proxies may hear the pump: show the one Home
        # Assistant would connect through (the best connectable path).
        best = bluetooth.async_last_service_info(hass, service_info.address, connectable=True)
        coordinator.set_rssi(best.rssi if best else service_info.rssi)

    @callback
    def _on_advertisement(
        service_info: bluetooth.BluetoothServiceInfoBleak, _change: bluetooth.BluetoothChange
    ) -> None:
        data = service_info.manufacturer_data.get(MOBIUS_COMPANY_ID)
        advert = parse_advertisement({MOBIUS_COMPANY_ID: data}) if data else None
        if advert is None:
            # Passive scanning: no manufacturer data, so match on the address.
            if service_info.address == link.address:
                _update_rssi(service_info)
            return
        if advert.serial.strip() != serial:
            return
        if service_info.address != link.address:
            link.set_address(service_info.address)
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_ADDRESS: service_info.address}
            )
        _update_rssi(service_info)

    for matcher in (
        # RSSI updates for the address in use, and any address carrying the
        # pump's serial (EcoTech manufacturer data) in case it changes.
        bluetooth.BluetoothCallbackMatcher(address=link.address, connectable=False),
        bluetooth.BluetoothCallbackMatcher(manufacturer_id=MOBIUS_COMPANY_ID, connectable=False),
    ):
        entry.async_on_unload(
            bluetooth.async_register_callback(
                hass, _on_advertisement, matcher, bluetooth.BluetoothScanningMode.ACTIVE
            )
        )
    last = bluetooth.async_last_service_info(hass, link.address, connectable=True)
    if last is not None:
        coordinator.set_rssi(last.rssi)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await link.close()
        raise
    entry.runtime_data = coordinator
    coordinator.options_snapshot = dict(entry.options)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: VorTechConfigEntry) -> None:
    # Also called when the pump's address is updated; only reload for options.
    if dict(entry.options) != entry.runtime_data.options_snapshot:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: VorTechConfigEntry) -> bool:
    """Unload one pump and free its Bluetooth connection."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded
