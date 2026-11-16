# SPDX-License-Identifier: GPL-2.0-only
"""Actions: scenes, schedule read/write and wave settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mobius import PumpMode, PumpParam, pump_schedule_from_dict, pump_schedule_to_dict
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import (
    DOMAIN,
    MAX_SCENE_MINUTES,
    SERVICE_GET_SCHEDULE,
    SERVICE_RESUME_SCHEDULE,
    SERVICE_SET_SCHEDULE,
    SERVICE_SET_WAVE,
    SERVICE_START_SCENE,
)

if TYPE_CHECKING:
    from .coordinator import VorTechCoordinator

ATTR_DEVICE_ID = "device_id"

_DEVICE = {vol.Required(ATTR_DEVICE_ID): cv.string}

START_SCENE_SCHEMA = vol.Schema(
    {
        **_DEVICE,
        vol.Required("scene"): cv.string,
        vol.Optional("minutes"): vol.All(vol.Coerce(float), vol.Range(min=0, max=MAX_SCENE_MINUTES)),
    }
)
SET_SCHEDULE_SCHEMA = vol.Schema({**_DEVICE, vol.Required("schedule"): [dict]})
SET_WAVE_SCHEMA = vol.Schema(
    {
        **_DEVICE,
        vol.Required("mode"): vol.In(
            ["ConstantSpeed", "ReefCrest", "Lagoon", "NutrientTransport", "TidalSwell",
             "ShortPulse", "Gyre", "ExpandingPulse"]
        ),
        vol.Required("speed"): vol.All(vol.Coerce(float), vol.Range(min=1, max=100)),
        vol.Optional("pulse_ms"): vol.All(vol.Coerce(int), vol.Range(min=250, max=2000)),
        vol.Optional("gyre_seconds"): vol.All(vol.Coerce(int), vol.Range(min=2, max=3600)),
        vol.Optional("start_ms"): vol.All(vol.Coerce(int), vol.Range(min=250, max=2000)),
        vol.Optional("end_ms"): vol.All(vol.Coerce(int), vol.Range(min=250, max=2000)),
    }
)


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> VorTechCoordinator:
    device = dr.async_get(hass).async_get(call.data[ATTR_DEVICE_ID])
    if device is not None:
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry and entry.domain == DOMAIN and entry.state is ConfigEntryState.LOADED:
                return entry.runtime_data
    raise ServiceValidationError("That device is not a loaded EcoTech VorTech pump")


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions (each handler is a real coroutine)."""

    async def start_scene(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        wanted = call.data["scene"]
        scene_id = None
        for scene in coordinator.data.scenes:
            if scene.name.lower() == wanted.lower() or str(scene.id) == wanted:
                scene_id = scene.id
        if scene_id is None and wanted.isdigit():
            scene_id = int(wanted)
        if scene_id is None:
            names = ", ".join(s.name for s in coordinator.data.scenes)
            raise ServiceValidationError(f"No scene called {wanted!r}. The pump has: {names}")
        await coordinator.async_start_scene(scene_id, call.data.get("minutes"))

    async def resume_schedule(call: ServiceCall) -> None:
        await _coordinator(hass, call).async_resume_schedule()

    async def get_schedule(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call)
        await coordinator.async_refresh()
        return {"schedule": pump_schedule_to_dict(coordinator.data.schedule)}

    async def set_schedule(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        try:
            points = pump_schedule_from_dict(call.data["schedule"])
        except (KeyError, ValueError, TypeError) as err:
            raise ServiceValidationError(f"Schedule not understood: {err}") from err
        if not points:
            raise ServiceValidationError("The schedule needs at least one block")
        await coordinator.async_write_schedule(points)

    async def set_wave(call: ServiceCall) -> None:
        coordinator = _coordinator(hass, call)
        mode = PumpMode[call.data["mode"]]
        params: dict[PumpParam, int] = {}
        if "pulse_ms" in call.data:
            params[PumpParam.Time] = call.data["pulse_ms"]
        if "gyre_seconds" in call.data:
            params[PumpParam.BigTime] = call.data["gyre_seconds"] * 1000
        if "start_ms" in call.data:
            params[PumpParam.StartTime] = call.data["start_ms"]
        if "end_ms" in call.data:
            params[PumpParam.EndTime] = call.data["end_ms"]
        await coordinator.async_set_wave(mode, call.data["speed"], params)

    hass.services.async_register(DOMAIN, SERVICE_START_SCENE, start_scene, schema=START_SCENE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_RESUME_SCHEDULE, resume_schedule, schema=vol.Schema(_DEVICE)
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SCHEDULE,
        get_schedule,
        schema=vol.Schema(_DEVICE),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, SERVICE_SET_SCHEDULE, set_schedule, schema=SET_SCHEDULE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SET_WAVE, set_wave, schema=SET_WAVE_SCHEMA)
