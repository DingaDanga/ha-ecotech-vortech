# SPDX-License-Identifier: GPL-2.0-only
"""Polling, controls and running statistics for one VorTech pump."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import time
from typing import Any

from mobius import (
    ConfigurationCache,
    FullPollResult,
    MobiusDevice,
    PrimitiveType,
    PumpMode,
    PumpParam,
    PumpPrimitiveValue,
    PumpSchedulePoint,
    SceneID,
    get_active_pump_block,
    parse_firmware_check,
    firmware_check_url,
    supported_pump_modes,
)
from mobius.constants import PUMP_MODE_PARAMS

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_APP_RELEASE_MINUTES,
    CONF_FIRMWARE_CHECK,
    CONF_FREE_PROXY,
    CONF_KEEP_CONNECTED,
    CONF_MIN_RSSI,
    CONF_OFF_HOLD_MINUTES,
    CONF_POLL_INTERVAL,
    CONF_TIME_SYNC,
    DEFAULT_APP_RELEASE_MINUTES,
    DEFAULT_FEED_MINUTES,
    DEFAULT_FIRMWARE_CHECK,
    DEFAULT_FREE_PROXY,
    DEFAULT_KEEP_CONNECTED,
    DEFAULT_MIN_RSSI,
    DEFAULT_OFF_HOLD_MINUTES,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TIME_SYNC,
    DOMAIN,
    FIRMWARE_CHECK_INTERVAL_SECONDS,
    MAX_SCENE_MINUTES,
    PROXY_COOLDOWN_SECONDS,
    PROXY_RELOAD_AFTER_SECONDS,
    PROXY_STUCK_SECONDS,
    STATIC_REFRESH_SECONDS,
    TIME_SYNC_INTERVAL_SECONDS,
    TIME_SYNC_MAX_DRIFT_SECONDS,
)
from . import proxy
from .pump import PumpLink, PumpReleased, PumpSignalWeak

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
# Polls may fail now and then over Bluetooth; entities only go unavailable
# after this many failures in a row.
FAILURES_BEFORE_UNAVAILABLE = 3
# Readings older than this don't feed the running totals (no guessing over
# a long gap, e.g. after a restart or while handed to the app).
MAX_INTEGRATION_GAP_SECONDS = 300
EXTRA_VALUES_INTERVAL_SECONDS = 0  # temperatures and RPM on every reading

# Modes the speed slider / wave-mode select can set without extra timing
# values. Others (Gyre, Pulse...) are kept as they are and only their speed
# is changed.
SIMPLE_MODES = (
    PumpMode.ConstantSpeed,
    PumpMode.ReefCrest,
    PumpMode.Lagoon,
    PumpMode.NutrientTransport,
    PumpMode.TidalSwell,
)


@dataclass
class PumpData:
    """Everything the entities show, from the last successful poll."""

    poll: FullPollResult
    polled_at: float
    extra_values: dict[str, Any] = field(default_factory=dict)

    # -- identity ------------------------------------------------------------
    @property
    def info(self) -> dict:
        return self.poll.device_info

    @property
    def firmware_versions(self) -> dict:
        return dict(self.poll.metadata.firmware_versions or {})

    @property
    def main_firmware(self) -> str | None:
        return getattr(self.poll.metadata, "firmware_version", None)

    # -- live readings -------------------------------------------------------
    @property
    def telemetry(self) -> dict:
        return self.poll.pump_telemetry or {}

    @property
    def speed_percent(self) -> float | None:
        # MotorSpeed keeps the last set speed while "All Off" holds the
        # motor, so report the motor as stopped then.
        if self.scene_id == SceneID.AllOff and not self.power_watts:
            return 0.0
        return self.telemetry.get("speed_percent")

    @property
    def motor_running(self) -> bool:
        return bool(self.power_watts) or bool(self.flow_gph) or (
            self.power_watts is None and (self.speed_percent or 0) > 0
        )

    @property
    def flow_gph(self) -> float | None:
        if not self.telemetry.get("gph_reliable"):
            return None
        return self.telemetry.get("gph")

    @property
    def power_watts(self) -> float | None:
        return self.telemetry.get("motor_power_watts")

    @property
    def operation_mode(self) -> str | None:
        return self.telemetry.get("operation_mode")

    @property
    def operation_state(self) -> str | None:
        state = self.poll.operation_state
        return state.name if state is not None else None

    @property
    def error_state(self) -> str | None:
        return self.info.get("error_state")

    # -- schedule ------------------------------------------------------------
    @property
    def schedule(self) -> list[PumpSchedulePoint]:
        return list(self.poll.pump_schedule_points or [])

    @property
    def active_point(self) -> PumpSchedulePoint | None:
        now = dt_util.now()
        return get_active_pump_block(self.schedule, now.hour * 60 + now.minute)

    @property
    def schedule_mode(self) -> str | None:
        point = self.active_point
        return point.pump.mode.name if point else None

    @property
    def schedule_speed_percent(self) -> float | None:
        point = self.active_point
        if point is None or PumpParam.MaxSpeed not in point.pump.params:
            return None
        return abs(point.pump.params[PumpParam.MaxSpeed]) / 10

    # -- scenes --------------------------------------------------------------
    @property
    def scenes(self) -> list:
        return [s for s in self.poll.configured_scenes if not s.is_empty]

    @property
    def current_scene(self):
        return self.poll.current_scene

    @property
    def scene_id(self) -> int | None:
        scene = self.current_scene
        return scene.id if scene else None

    def scene_name(self, scene_id: int | None) -> str | None:
        if scene_id is None:
            return None
        for scene in self.poll.configured_scenes:
            if scene.id == scene_id and scene.name:
                return scene.name
        try:
            return SceneID(scene_id).name
        except ValueError:
            return f"Scene {scene_id}"

    @property
    def pump_on(self) -> bool:
        """False while the All Off scene holds the pump."""
        return self.scene_id != SceneID.AllOff

    @property
    def feeding(self) -> bool:
        """Paused: the Feed button, the Pump switch (both use "All Off") or
        the pump's own Feed Mode scene."""
        return self.scene_id in (SceneID.FeedMode, SceneID.AllOff)

    @property
    def scene_remaining_seconds(self) -> float | None:
        scene = self.current_scene
        if scene is None:
            return None
        # The device counts down; count down locally between polls too.
        return max(0.0, scene.duration_seconds - (time.time() - self.polled_at))

    # -- other ---------------------------------------------------------------
    @property
    def battery_backup_percent(self) -> float | None:
        info = self.poll.battery_backup
        return info.speed / 10 if info else None

    @property
    def battery_backup_max_percent(self) -> float | None:
        info = self.poll.battery_backup
        return info.max_speed / 10 if info and info.max_speed else None

    @property
    def advanced(self):
        return self.poll.metadata.advanced_features

    @property
    def clock_drift_seconds(self) -> int | None:
        epoch = self.poll.metadata.epoch
        return None if epoch is None else int(self.polled_at - epoch)

    @property
    def max_flow_gph(self) -> int | None:
        return self.telemetry.get("maximum_gph")


class VorTechCoordinator(DataUpdateCoordinator[PumpData]):
    """Polls one pump and runs its controls."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, link: PumpLink) -> None:
        interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {link.name}",
            update_interval=timedelta(seconds=interval),
            always_update=True,
        )
        self.link = link
        link.keep_connected = entry.options.get(CONF_KEEP_CONNECTED, DEFAULT_KEEP_CONNECTED)
        link.min_rssi = int(entry.options.get(CONF_MIN_RSSI, DEFAULT_MIN_RSSI))
        # Stuck-proxy recovery: when the pump was last reachable, and what has
        # been tried since it went missing.
        self._down_since: float | None = None
        self._proxy_asked_at: float | None = None
        self._proxy_reloaded_at: float | None = None
        self.proxy_frees = 0
        self.proxy_last_action: str | None = None
        self.cache = ConfigurationCache(static_refresh_interval=STATIC_REFRESH_SECONDS)
        self._primitive: PrimitiveType | None = None
        self._model = None
        self._supported: set | None = None
        self._failures = 0
        self._last_extra_read = 0.0
        self._last_time_check = 0.0
        self._last_firmware_check = 0.0
        self.rssi: int | None = None
        self.firmware_latest: dict[str, str] = {}
        self.firmware_release_url: str | None = None
        self.last_time_sync: datetime | None = None
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.stats: dict[str, Any] = {
            "run_seconds": 0.0,
            "off_seconds": 0.0,
            "energy_wh": 0.0,
            "pumped_litres": 0.0,
            "feeds": 0,
            "last_feed": None,
            "feed_minutes": DEFAULT_FEED_MINUTES,
        }
        self._last_sample: tuple[float, float, float, bool] | None = None  # time, watts, gph, on
        self._last_scene_id: int | None = None
        self.options_snapshot: dict = {}
        link.add_listener(self._on_link_change)

    # ---- options -----------------------------------------------------------
    def option(self, key: str, default):
        return self.config_entry.options.get(key, default)

    @property
    def off_hold_seconds(self) -> int:
        minutes = min(self.option(CONF_OFF_HOLD_MINUTES, DEFAULT_OFF_HOLD_MINUTES), MAX_SCENE_MINUTES)
        return int(minutes * 60)

    @property
    def feed_minutes(self) -> float:
        return float(self.stats.get("feed_minutes") or DEFAULT_FEED_MINUTES)

    # ---- storage -----------------------------------------------------------
    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if stored:
            self.stats.update(stored)

    @callback
    def _save_later(self) -> None:
        self._store.async_delay_save(lambda: dict(self.stats), 60)

    async def async_save_now(self) -> None:
        await self._store.async_save(dict(self.stats))

    # ---- link events -------------------------------------------------------
    @callback
    def _on_link_change(self) -> None:
        self.async_update_listeners()

    @callback
    def set_rssi(self, rssi: int | None) -> None:
        self.rssi = rssi

    # ---- polling -----------------------------------------------------------
    async def _async_update_data(self) -> PumpData:
        try:
            data = await self.link.run(self._poll)
        except PumpReleased:
            if self.data is not None:
                return self.data
            raise UpdateFailed("Bluetooth is handed to the Mobius app") from None
        except Exception as err:  # noqa: BLE001 - any Bluetooth/protocol failure
            self._failures += 1
            _LOGGER.debug("Poll failed (%d in a row): %s", self._failures, err)
            if not isinstance(err, PumpSignalWeak):
                await self._maybe_free_proxy()
            if self.data is not None and self._failures < FAILURES_BEFORE_UNAVAILABLE:
                return self.data
            raise UpdateFailed(f"Pump not answering: {err}") from err
        self._failures = 0
        self._down_since = None
        self._proxy_asked_at = None
        self._update_stats(data)
        await self._maybe_check_firmware(data)
        return data

    async def _maybe_free_proxy(self) -> None:
        """Makes a Bluetooth proxy let go of a dead connection to the pump.

        Runs only after the pump has been out of reach for a while: the proxy
        that last carried the link is asked to disconnect the pump, and if
        Home Assistant's records still show it holding the pump a minute
        later, the proxy is reloaded. Then nothing more for the cool-down.
        """
        now = time.monotonic()
        if self._down_since is None:
            self._down_since = now
            return
        if not self.option(CONF_FREE_PROXY, DEFAULT_FREE_PROXY):
            return
        if now - self._down_since < PROXY_STUCK_SECONDS or self.link.is_connected:
            return
        if self._proxy_reloaded_at is not None and now - self._proxy_reloaded_at < PROXY_COOLDOWN_SECONDS:
            return
        address = self.link.address
        try:
            found = proxy.proxies(self.hass, self.link.connect_source)
            if not found:
                return
            if self._proxy_asked_at is None:
                self._proxy_asked_at = now
                for source, entry in found:
                    if proxy.holds_address(source, address) is False:
                        continue
                    if await proxy.ask_disconnect(entry, address):
                        self.proxy_frees += 1
                        self.proxy_last_action = f"asked {entry.title} to disconnect"
                        _LOGGER.warning(
                            "%s: out of reach for %d s; asked Bluetooth proxy %s to drop its old connection",
                            self.link.name, now - self._down_since, entry.title,
                        )
                return
            if now - self._proxy_asked_at < PROXY_RELOAD_AFTER_SECONDS:
                return
            for source, entry in found:
                if proxy.holds_address(source, address) is not True:
                    continue
                self._proxy_reloaded_at = now
                self._proxy_asked_at = None
                self.proxy_frees += 1
                self.proxy_last_action = f"reloaded {entry.title}"
                _LOGGER.warning(
                    "%s: Bluetooth proxy %s is still holding a dead connection; reloading it",
                    self.link.name, entry.title,
                )
                self.hass.async_create_task(proxy.reload_proxy(self.hass, entry))
                return
            # Nothing is holding the pump: it is simply out of reach. Try
            # again after the cool-down rather than on every reading.
            self._proxy_reloaded_at = now
            self._proxy_asked_at = None
        except Exception:  # noqa: BLE001 - recovery must never break polling
            _LOGGER.debug("%s: proxy recovery failed", self.link.name, exc_info=True)

    async def _poll(self, device: MobiusDevice) -> PumpData:
        if self._supported is None:
            try:
                self._supported = {s.attr_id for s in await device.get_supported_attributes()}
            except Exception:  # noqa: BLE001
                self._supported = None
        poll = await device.get_full_poll_batch(
            primitive=self._primitive,
            model=self._model,
            supported_attribute_ids=self._supported,
            cache=self.cache,
        )
        if poll.attribute_table_changed:
            self._supported = None
        self._primitive = poll.primitive or self._primitive
        self._model = poll.model or self._model
        now = time.time()
        extra = self.data.extra_values if self.data else {}
        if now - self._last_extra_read >= EXTRA_VALUES_INTERVAL_SECONDS:
            try:
                extra = await device.get_extra_physical_values()
                self._last_extra_read = now
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Extra readings not available", exc_info=True)
        data = PumpData(poll=poll, polled_at=now, extra_values=extra)
        if self.option(CONF_TIME_SYNC, DEFAULT_TIME_SYNC):
            await self._maybe_sync_time(device, data)
        return data

    async def _maybe_sync_time(self, device: MobiusDevice, data: PumpData) -> None:
        now = time.time()
        if now - self._last_time_check < TIME_SYNC_INTERVAL_SECONDS:
            return
        drift = data.clock_drift_seconds
        if drift is None:
            return
        self._last_time_check = now
        tz = str(self.hass.config.time_zone)
        tz_wrong = data.poll.metadata.olson_tz not in (None, tz)
        if abs(drift) <= TIME_SYNC_MAX_DRIFT_SECONDS and not tz_wrong:
            return
        _LOGGER.info("Setting the pump clock (drift %ss, time zone %s)", drift, data.poll.metadata.olson_tz)
        try:
            if tz_wrong:
                await device.set_time_zone(tz)
            await device.set_time_to_now()
            self.last_time_sync = dt_util.utcnow()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Could not set the pump's clock", exc_info=True)

    async def _maybe_check_firmware(self, data: PumpData) -> None:
        if not self.option(CONF_FIRMWARE_CHECK, DEFAULT_FIRMWARE_CHECK):
            return
        now = time.time()
        if now - self._last_firmware_check < FIRMWARE_CHECK_INTERVAL_SECONDS:
            return
        images = data.poll.metadata.firmware_images or []
        if not images:
            return
        self._last_firmware_check = now
        session = async_get_clientsession(self.hass)
        latest: dict[str, str] = {}
        release_url = None
        for image in images:
            label = image.firmware_type.name
            try:
                async with session.get(firmware_check_url(image.image_id, image.version), timeout=20) as resp:
                    check = parse_firmware_check(await resp.json(content_type=None))
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Firmware check failed for %s", label, exc_info=True)
                continue
            latest[label] = check.update.version if check.update else image.version
            if check.update and check.update.changelog_url:
                release_url = check.update.changelog_url
        if latest:
            self.firmware_latest = latest
            self.firmware_release_url = release_url

    # ---- statistics --------------------------------------------------------
    @callback
    def _update_stats(self, data: PumpData) -> None:
        now = data.polled_at
        watts = float(data.power_watts or 0)
        gph = float(data.flow_gph or 0)
        running = data.motor_running
        if self._last_sample is not None:
            then, last_watts, last_gph, last_running = self._last_sample
            gap = now - then
            if 0 < gap <= MAX_INTEGRATION_GAP_SECONDS:
                self.stats["energy_wh"] += (watts + last_watts) / 2 * gap / 3600
                self.stats["pumped_litres"] += (gph + last_gph) / 2 * gap / 3600 * 3.785411784
                if running and last_running:
                    self.stats["run_seconds"] += gap
                elif not running and not last_running:
                    self.stats["off_seconds"] += gap
                else:
                    self.stats["run_seconds"] += gap / 2
                    self.stats["off_seconds"] += gap / 2
        self._last_sample = (now, watts, gph, running)
        scene_id = data.scene_id
        paused = (SceneID.FeedMode, SceneID.AllOff)
        if scene_id in paused and self._last_scene_id not in paused:
            self._count_feed()
        self._last_scene_id = scene_id
        self._save_later()

    @callback
    def _count_feed(self) -> None:
        self.stats["feeds"] = int(self.stats.get("feeds", 0)) + 1
        self.stats["last_feed"] = dt_util.utcnow().isoformat()

    async def async_set_feed_minutes(self, minutes: float) -> None:
        self.stats["feed_minutes"] = minutes
        await self.async_save_now()
        self.async_update_listeners()

    # ---- controls ----------------------------------------------------------
    async def _control(self, job) -> None:
        try:
            await self.link.run(job)
        except PumpReleased as err:
            raise HomeAssistantError(
                "Bluetooth is handed to the Mobius app at the moment. "
                "Press 'Reconnect now' to take it back."
            ) from err
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"The pump didn't take the change: {err}") from err
        await self.async_refresh()

    async def async_pump_off(self) -> None:
        seconds = self.off_hold_seconds
        await self._control(lambda d: d.start_scene(SceneID.AllOff, seconds))

    async def async_pump_on(self) -> None:
        await self._control(lambda d: d.resume_schedule())

    async def async_feed(self, minutes: float | None = None) -> None:
        """Stops the pump completely for the feed time ("All Off" for that
        long), then it goes back to its schedule by itself. The pump's own
        Feed Mode scene only slows it to the speed set in the Mobius app."""
        seconds = int(min(minutes if minutes is not None else self.feed_minutes, MAX_SCENE_MINUTES) * 60)
        await self._control(lambda d: d.start_scene(SceneID.AllOff, seconds))

    async def async_start_scene(self, scene_id: int, minutes: float | None = None) -> None:
        seconds = None if minutes is None else int(min(minutes, MAX_SCENE_MINUTES) * 60)
        await self._control(lambda d: d.start_scene(scene_id, seconds))

    async def async_resume_schedule(self) -> None:
        await self._control(lambda d: d.resume_schedule())

    async def async_reboot(self) -> None:
        await self._control(lambda d: d.reboot())

    async def async_sync_time(self) -> None:
        tz = str(self.hass.config.time_zone)

        async def job(device: MobiusDevice) -> None:
            await device.set_time_zone(tz)
            await device.set_time_to_now()

        await self._control(job)
        self.last_time_sync = dt_util.utcnow()
        self._last_time_check = time.time()

    async def async_set_battery_backup(self, percent: float) -> None:
        self.cache.invalidate_static()
        await self._control(lambda d: d.set_battery_backup_speed(percent))

    async def async_set_advanced(self, **kwargs) -> None:
        self.cache.invalidate_static()

        async def job(device: MobiusDevice) -> None:
            result = await device.set_advanced_features(**kwargs)
            failed = {k: v for k, v in result.items() if v is not None}
            if failed:
                raise HomeAssistantError(f"Not accepted: {failed}")

        await self._control(job)

    # ---- schedule writes ---------------------------------------------------
    def _require_data(self) -> PumpData:
        if self.data is None:
            raise HomeAssistantError("No reading from the pump yet")
        return self.data

    async def async_write_schedule(self, points: list[PumpSchedulePoint]) -> None:
        primitive, model = self._primitive, self._model
        await self._control(lambda d: d.set_pump_schedule(points, primitive_type=primitive, model=model))

    def _edited_schedule(self, mode: PumpMode | None, speed_permille: int | None) -> list[PumpSchedulePoint]:
        """The schedule with the active point's mode and/or speed changed;
        every other point is left as it is."""
        data = self._require_data()
        points = data.schedule
        active = data.active_point
        if active is None:
            new_mode = mode or PumpMode.ConstantSpeed
            speed = speed_permille if speed_permille is not None else 500
            return [PumpSchedulePoint(0, 0, PumpPrimitiveValue(new_mode, {PumpParam.MaxSpeed: speed}))]
        index = points.index(active)
        params = dict(active.pump.params)
        new_mode = active.pump.mode
        if mode is not None and mode != active.pump.mode:
            if mode not in SIMPLE_MODES:
                raise HomeAssistantError(f"{mode.name} needs timing values: use the set_wave action")
            new_mode = mode
            params = {PumpParam.MaxSpeed: params.get(PumpParam.MaxSpeed, 500)}
        if speed_permille is not None:
            if PumpParam.MaxSpeed not in PUMP_MODE_PARAMS.get(new_mode, []):
                raise HomeAssistantError(f"The {new_mode.name} block has no speed to set")
            sign = -1 if params.get(PumpParam.MaxSpeed, 0) < 0 else 1
            params[PumpParam.MaxSpeed] = sign * speed_permille
        points[index] = PumpSchedulePoint(
            active.time_minutes, active.flags, PumpPrimitiveValue(new_mode, params)
        )
        return points

    async def async_set_speed(self, percent: float) -> None:
        permille = max(10, min(1000, int(round(percent)) * 10))
        await self.async_write_schedule(self._edited_schedule(None, permille))

    async def async_set_mode(self, mode: PumpMode) -> None:
        await self.async_write_schedule(self._edited_schedule(mode, None))

    async def async_set_wave(self, mode: PumpMode, percent: float, params: dict[PumpParam, int]) -> None:
        """Replaces the active block with `mode` at `percent` plus timing params."""
        data = self._require_data()
        points = data.schedule
        active = data.active_point
        values = {PumpParam.MaxSpeed: int(round(percent)) * 10, **params}
        new_point_value = PumpPrimitiveValue(mode, {p: values[p] for p in PUMP_MODE_PARAMS[mode] if p in values})
        missing = [p.name for p in PUMP_MODE_PARAMS[mode] if p not in values]
        if missing:
            raise HomeAssistantError(f"{mode.name} needs: {', '.join(missing)}")
        if active is None:
            points = [PumpSchedulePoint(0, 0, new_point_value)]
        else:
            points[points.index(active)] = PumpSchedulePoint(active.time_minutes, active.flags, new_point_value)
        await self.async_write_schedule(points)

    def supported_modes(self) -> list[PumpMode]:
        if self._primitive is None:
            return list(SIMPLE_MODES)
        return [m for m in supported_pump_modes(self._primitive) if m in SIMPLE_MODES]

    # ---- app hand-over -----------------------------------------------------
    async def async_release_for_app(self) -> None:
        minutes = self.option(CONF_APP_RELEASE_MINUTES, DEFAULT_APP_RELEASE_MINUTES)
        await self.link.release(minutes)
        self.async_update_listeners()

    async def async_reconnect(self) -> None:
        self.link.cancel_release()
        await self.async_refresh()

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.async_save_now()
        await self.link.close()

    @property
    def link_state(self) -> str:
        if self.link.released_until is not None:
            return "released"
        if self.link.is_connected:
            return "connected"
        if not self.link.keep_connected and self.last_update_success:
            return "on_demand"
        return "disconnected"
