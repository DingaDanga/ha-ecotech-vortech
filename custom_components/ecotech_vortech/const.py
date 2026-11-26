# SPDX-License-Identifier: GPL-2.0-only
"""Constants for the EcoTech VorTech (Bluetooth) integration."""

from __future__ import annotations

DOMAIN = "ecotech_vortech"
MANUFACTURER = "EcoTech Marine"

# Advertised by every Mobius-protocol device (see the manifest).
MOBIUS_SERVICE_UUID = "01ff0100-ba5e-f4ee-5ca1-eb1e5e4b1ce0"
MOBIUS_COMPANY_ID = 514  # 0x0202, EcoTech Marine

CONF_SERIAL = "serial"
CONF_MODEL = "model"

# Options
CONF_POLL_INTERVAL = "poll_interval"
CONF_KEEP_CONNECTED = "keep_connected"
CONF_OFF_HOLD_MINUTES = "off_hold_minutes"
CONF_APP_RELEASE_MINUTES = "app_release_minutes"
CONF_TANK_VOLUME = "tank_volume"
CONF_TIME_SYNC = "time_sync"
CONF_FIRMWARE_CHECK = "firmware_check"
CONF_MIN_RSSI = "min_rssi"
CONF_FREE_PROXY = "free_stuck_proxy"

DEFAULT_POLL_INTERVAL = 30
DEFAULT_KEEP_CONNECTED = True
# A scene duration is a u16 number of seconds on the wire: 1092 minutes max.
MAX_SCENE_MINUTES = 1092
DEFAULT_OFF_HOLD_MINUTES = 720
DEFAULT_APP_RELEASE_MINUTES = 15
DEFAULT_TANK_VOLUME = 0
DEFAULT_TIME_SYNC = True
DEFAULT_FIRMWARE_CHECK = True
# Weakest Bluetooth path the integration will connect through. A far adapter
# that only just hears the pump makes a link that fails within minutes.
DEFAULT_MIN_RSSI = -80
MIN_RSSI_OFF = -100
DEFAULT_FREE_PROXY = True

# A proxy holding a dead connection keeps the pump silent. After this long
# without the pump the proxy is asked to let go, then reloaded if it still
# holds the pump, then left alone for the cool-down.
PROXY_STUCK_SECONDS = 90
PROXY_RELOAD_AFTER_SECONDS = 60
PROXY_COOLDOWN_SECONDS = 600

DEFAULT_FEED_MINUTES = 10

# Static attributes (identity, firmware, flow range...) are re-read this often.
STATIC_REFRESH_SECONDS = 3600
# Clock is corrected when it drifts by more than this, checked every 6 hours.
TIME_SYNC_INTERVAL_SECONDS = 6 * 3600
TIME_SYNC_MAX_DRIFT_SECONDS = 30
FIRMWARE_CHECK_INTERVAL_SECONDS = 12 * 3600

# Speeds the pump accepts (permille of full power), as the app allows.
SPEED_MIN_PERCENT = 1
SPEED_MAX_PERCENT = 100

US_GALLON_LITRES = 3.785411784

SERVICE_START_SCENE = "start_scene"
SERVICE_RESUME_SCHEDULE = "resume_schedule"
SERVICE_GET_SCHEDULE = "get_schedule"
SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_SET_WAVE = "set_wave"
