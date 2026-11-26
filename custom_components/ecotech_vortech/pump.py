# SPDX-License-Identifier: GPL-2.0-only
"""Bluetooth link to one VorTech pump, through Home Assistant's Bluetooth stack.

python-mobius talks the Mobius protocol; this module only decides how the
connection is made: always through Home Assistant's own Bluetooth (local
adapters and ESPHome Bluetooth proxies alike), with the address Home
Assistant last saw the pump on, and with bleak-retry-connector's retries and
service cache.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from mobius import MobiusDevice
from mobius.device import CHAR_RX_DATA, CHAR_RX_FINAL, write_size_for_mtu

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class PumpNotFound(ConnectionError):
    """Home Assistant has no connectable Bluetooth path to the pump."""


class PumpSignalWeak(ConnectionError):
    """The only Bluetooth path to the pump is too weak to hold a connection."""


class PumpReleased(ConnectionError):
    """The link has been handed to the Mobius app for a while."""


class _HassMobiusDevice(MobiusDevice):
    """MobiusDevice that connects through Home Assistant's Bluetooth."""

    def __init__(self, link: PumpLink) -> None:
        super().__init__(device=link.address)
        self._link = link

    def _ble_device(self) -> BLEDevice | None:
        return bluetooth.async_ble_device_from_address(
            self._link.hass, self._link.address, connectable=True
        )

    async def connect(self) -> None:  # noqa: D102 - replaces the library's
        self._rx_buffer.clear()
        self._rx_trace = []
        ble_device = self._ble_device()
        if ble_device is None:
            raise PumpNotFound(
                f"no Bluetooth adapter or proxy can currently reach {self._link.address}"
            )
        self.address = ble_device.address
        info = bluetooth.async_last_service_info(self._link.hass, self.address, connectable=True)
        if info is not None:
            if info.rssi is not None and info.rssi < self._link.min_rssi:
                raise PumpSignalWeak(
                    f"best Bluetooth path to {self.address} is {info.rssi} dBm via {info.source}, "
                    f"below the {self._link.min_rssi} dBm minimum"
                )
            # The pump stops advertising while connected, so this is the last
            # signal reading of the path the connection uses.
            self._link.connect_rssi = info.rssi
            self._link.connect_source = info.source
        self._client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            self._link.name,
            disconnected_callback=self._link.on_disconnected,
            ble_device_callback=lambda: self._ble_device() or ble_device,
            max_attempts=3,
        )
        try:
            await self._client.start_notify(CHAR_RX_DATA, self._on_rx_data)
            await self._client.start_notify(CHAR_RX_FINAL, self._on_rx_final)
            self.mtu = write_size_for_mtu(self._negotiated_mtu())
        except Exception:
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            raise


class PumpLink:
    """One pump's connection: opened on demand, kept open between polls
    (or closed after each one), and handed to the Mobius app on request.

    The pump accepts a single Bluetooth connection, so while this link holds
    it the Mobius phone app can't connect.
    """

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        self.hass = hass
        self.address = address
        self.name = name
        self.keep_connected = True
        self.device = _HassMobiusDevice(self)
        self._lock = asyncio.Lock()
        self._released_until: float | None = None
        self._listeners: list[Callable[[], None]] = []
        self.connected_at: float | None = None
        self.connect_count = 0
        self.last_error: str | None = None
        self.connect_rssi: int | None = None
        self.connect_source: str | None = None
        self.min_rssi: int = -100

    # ---- state -------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self.device.is_connected

    @property
    def released_until(self) -> float | None:
        """time.time() at which the app release ends, None when not released."""
        if self._released_until is not None and time.time() >= self._released_until:
            self._released_until = None
        return self._released_until

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def on_disconnected(self, _client) -> None:
        _LOGGER.debug("%s: Bluetooth connection closed", self.name)
        self.connected_at = None
        for listener in list(self._listeners):
            listener()

    def set_address(self, address: str) -> None:
        if address != self.address:
            _LOGGER.info("%s: pump now seen at %s (was %s)", self.name, address, self.address)
            self.address = address

    # ---- connection ----------------------------------------------------------

    async def _ensure_connected(self) -> None:
        if self.released_until is not None:
            raise PumpReleased("Bluetooth is handed to the Mobius app")
        if self.device.is_connected:
            return
        await self.device.connect()
        self.connected_at = time.time()
        self.connect_count += 1
        _LOGGER.debug("%s: connected (attempt %d)", self.name, self.connect_count)

    async def run(self, job: Callable[[MobiusDevice], object]):
        """Runs `job(device)` on a connected device, one job at a time."""
        async with self._lock:
            try:
                await self._ensure_connected()
                result = await job(self.device)
                self.last_error = None
                return result
            except PumpReleased:
                raise
            except Exception as err:
                self.last_error = f"{type(err).__name__}: {err}"
                await self._disconnect()
                raise
            finally:
                if not self.keep_connected:
                    await self._disconnect()

    async def _disconnect(self) -> None:
        try:
            await self.device.disconnect()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("%s: error while disconnecting", self.name, exc_info=True)
        self.connected_at = None

    async def release(self, minutes: float) -> None:
        """Closes the connection and keeps it closed for `minutes`, so the
        Mobius app can connect to the pump."""
        async with self._lock:
            self._released_until = time.time() + minutes * 60
            await self._disconnect()

    def cancel_release(self) -> None:
        self._released_until = None

    async def close(self) -> None:
        async with self._lock:
            await self._disconnect()
