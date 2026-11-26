# SPDX-License-Identifier: GPL-2.0-only
"""Config flow: pumps are found by Home Assistant's Bluetooth discovery."""

from __future__ import annotations

import asyncio
from typing import Any

from mobius import parse_advertisement
from mobius.constants import Model, enum_or_none
import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import selector

from .pump import PumpLink
from .const import (
    CONF_APP_RELEASE_MINUTES,
    CONF_FIRMWARE_CHECK,
    CONF_FREE_PROXY,
    CONF_KEEP_CONNECTED,
    CONF_MIN_RSSI,
    CONF_MODEL,
    CONF_OFF_HOLD_MINUTES,
    CONF_POLL_INTERVAL,
    CONF_SERIAL,
    CONF_TANK_VOLUME,
    CONF_TIME_SYNC,
    DEFAULT_APP_RELEASE_MINUTES,
    DEFAULT_FIRMWARE_CHECK,
    DEFAULT_FREE_PROXY,
    DEFAULT_KEEP_CONNECTED,
    DEFAULT_MIN_RSSI,
    DEFAULT_OFF_HOLD_MINUTES,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TANK_VOLUME,
    DEFAULT_TIME_SYNC,
    DOMAIN,
    MAX_SCENE_MINUTES,
    MOBIUS_COMPANY_ID,
)


def _describe(info: BluetoothServiceInfoBleak) -> tuple[str, str, str] | None:
    """(serial, model label, title) of a Mobius advertisement; None when the
    advertisement doesn't carry the manufacturer data (e.g. passive scan)."""
    advert = parse_advertisement(info.manufacturer_data)
    if advert is None:
        return None
    serial = advert.serial.strip()
    label = _label_for_model(advert.model_raw)
    return serial, label, f"{label} {serial[-4:]}"


def _label_for_model(model_raw: int | None) -> str:
    model = enum_or_none(Model, model_raw) if model_raw is not None else None
    label = model.name if model else "VorTech"
    if label.startswith("VorTech") and label != "VorTech":
        label = "VorTech " + label.removeprefix("VorTech")
    return label


async def _read_identity(hass, info: BluetoothServiceInfoBleak) -> tuple[str, str, str] | None:
    """Connects once to read the serial number and model, for proxies that
    don't pass on the advertisement's manufacturer data (passive scanning)."""
    link = PumpLink(hass, info.address, "setup")
    link.keep_connected = False
    try:
        device_info = await asyncio.wait_for(link.run(lambda d: d.get_device_info()), 60)
    except Exception:  # noqa: BLE001
        return None
    finally:
        await link.close()
    serial = (device_info.get("serial") or "").strip()
    if not serial:
        return None
    label = _label_for_model(device_info.get("model_raw"))
    return serial, label, f"{label} {serial[-4:]}"


def _is_mobius(info: BluetoothServiceInfoBleak) -> bool:
    # The name or EcoTech's manufacturer data, not the service UUID alone:
    # a busy local adapter can attach stale service UUIDs to other devices.
    return "mobius" in (info.name or "").lower() or (
        MOBIUS_COMPANY_ID in info.manufacturer_data
        and parse_advertisement({MOBIUS_COMPANY_ID: info.manufacturer_data[MOBIUS_COMPANY_ID]}) is not None
    )


class VorTechConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a pump."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, tuple[BluetoothServiceInfoBleak, tuple[str, str, str] | None]] = {}
        self._chosen: tuple[BluetoothServiceInfoBleak, tuple[str, str, str] | None] | None = None

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        if not _is_mobius(discovery_info):
            return self.async_abort(reason="not_supported")
        described = _describe(discovery_info)
        # Without manufacturer data (passive scanning) the serial is read on
        # confirm; until then the address identifies the discovery.
        await self.async_set_unique_id(described[0] if described else discovery_info.address)
        self._abort_if_unique_id_configured(updates={CONF_ADDRESS: discovery_info.address})
        self._abort_if_address_configured(discovery_info.address)
        self._chosen = (discovery_info, described)
        self.context["title_placeholders"] = {
            "name": described[2] if described else f"EcoTech VorTech ({discovery_info.address})"
        }
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._chosen is not None
        info, described = self._chosen
        if user_input is not None:
            if described is None:
                described = await _read_identity(self.hass, info)
                if described is None:
                    return self.async_abort(reason="cannot_connect")
                await self.async_set_unique_id(described[0], raise_on_progress=False)
                self._abort_if_unique_id_configured(updates={CONF_ADDRESS: info.address})
            return self._create(info, *described)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self.context["title_placeholders"]["name"],
                "address": info.address,
                "rssi": str(info.rssi),
            },
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            info, described = self._discovered[user_input[CONF_ADDRESS]]
            if described is None:
                described = await _read_identity(self.hass, info)
                if described is None:
                    return self.async_abort(reason="cannot_connect")
            await self.async_set_unique_id(described[0], raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self._create(info, *described)

        configured = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            if not _is_mobius(info):
                continue
            described = _describe(info)
            if described is not None and described[0] in configured:
                continue
            if any(
                entry.data.get(CONF_ADDRESS) == info.address for entry in self._async_current_entries()
            ):
                continue
            self._discovered[info.address] = (info, described)
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{d[2] if d else info.name or 'Mobius'} ({address}, {info.rssi} dBm)"
                            for address, (info, d) in self._discovered.items()
                        }
                    )
                }
            ),
        )

    @callback
    def _abort_if_address_configured(self, address: str) -> None:
        for entry in self._async_current_entries(include_ignore=False):
            if entry.data.get(CONF_ADDRESS) == address:
                raise AbortFlow("already_configured")

    @callback
    def _create(self, info: BluetoothServiceInfoBleak, serial: str, label: str, title: str) -> ConfigFlowResult:
        return self.async_create_entry(
            title=title,
            data={CONF_ADDRESS: info.address, CONF_SERIAL: serial, CONF_MODEL: label},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return VorTechOptionsFlow()


def _minutes(maximum: int) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1, max=maximum, step=1, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX
        )
    )


class VorTechOptionsFlow(OptionsFlow):
    """Polling, connection and control settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POLL_INTERVAL, default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=600, step=5, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_KEEP_CONNECTED, default=options.get(CONF_KEEP_CONNECTED, DEFAULT_KEEP_CONNECTED)
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_MIN_RSSI, default=options.get(CONF_MIN_RSSI, DEFAULT_MIN_RSSI)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=-100, max=-40, step=1, unit_of_measurement="dBm", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_FREE_PROXY, default=options.get(CONF_FREE_PROXY, DEFAULT_FREE_PROXY)
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_OFF_HOLD_MINUTES, default=options.get(CONF_OFF_HOLD_MINUTES, DEFAULT_OFF_HOLD_MINUTES)
                ): _minutes(MAX_SCENE_MINUTES),
                vol.Required(
                    CONF_APP_RELEASE_MINUTES,
                    default=options.get(CONF_APP_RELEASE_MINUTES, DEFAULT_APP_RELEASE_MINUTES),
                ): _minutes(240),
                vol.Required(
                    CONF_TANK_VOLUME, default=options.get(CONF_TANK_VOLUME, DEFAULT_TANK_VOLUME)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=20000, step=1, unit_of_measurement="L", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_TIME_SYNC, default=options.get(CONF_TIME_SYNC, DEFAULT_TIME_SYNC)
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_FIRMWARE_CHECK, default=options.get(CONF_FIRMWARE_CHECK, DEFAULT_FIRMWARE_CHECK)
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
