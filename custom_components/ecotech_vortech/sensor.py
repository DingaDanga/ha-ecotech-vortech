# SPDX-License-Identifier: GPL-2.0-only
"""Sensors: live readings, running totals for statistics, and diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mobius import ErrorState, OperationMode, OperationState

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    UnitOfElectricPotential,
    UnitOfTemperature,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import VorTechConfigEntry
from .const import CONF_TANK_VOLUME, DEFAULT_TANK_VOLUME, US_GALLON_LITRES
from .coordinator import VorTechCoordinator
from .entity import VorTechEntity


def _enum_options(enum_cls) -> list[str]:
    return [m.name.lower() for m in enum_cls]


def _lower(value: str | None) -> str | None:
    return value.lower() if value else None


def _last_feed(c: VorTechCoordinator) -> datetime | None:
    value = c.stats.get("last_feed")
    return dt_util.parse_datetime(value) if value else None


def _turnover(c: VorTechCoordinator) -> float | None:
    volume = c.option(CONF_TANK_VOLUME, DEFAULT_TANK_VOLUME)
    gph = c.data.flow_gph
    if not volume or gph is None:
        return None
    return round(gph * US_GALLON_LITRES / volume, 1)


def _scene_remaining(c: VorTechCoordinator) -> float | None:
    remaining = c.data.scene_remaining_seconds
    return None if remaining is None else round(remaining / 60, 1)


@dataclass(frozen=True, kw_only=True)
class VorTechSensorDescription(SensorEntityDescription):
    value: Callable[[VorTechCoordinator], Any]
    attrs: Callable[[VorTechCoordinator], dict[str, Any]] | None = None
    exists: Callable[[VorTechCoordinator], bool] = lambda c: True


SENSORS: tuple[VorTechSensorDescription, ...] = (
    # ---- live readings (kept as long-term statistics) ---------------------------
    VorTechSensorDescription(
        key="motor_speed",
        translation_key="motor_speed",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value=lambda c: c.data.speed_percent,
    ),
    VorTechSensorDescription(
        key="flow",
        translation_key="flow",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.GALLONS_PER_HOUR,
        suggested_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value=lambda c: c.data.flow_gph,
        exists=lambda c: c.data.telemetry.get("gph_reliable", False),
    ),
    VorTechSensorDescription(
        key="motor_power",
        translation_key="motor_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda c: c.data.power_watts,
        exists=lambda c: c.data.power_watts is not None,
    ),
    VorTechSensorDescription(
        key="turnover",
        translation_key="turnover",
        native_unit_of_measurement="×/h",
        state_class=SensorStateClass.MEASUREMENT,
        value=_turnover,
        exists=lambda c: bool(c.option(CONF_TANK_VOLUME, DEFAULT_TANK_VOLUME)),
    ),
    # ---- what it is doing -----------------------------------------------------
    VorTechSensorDescription(
        key="operation_mode",
        translation_key="operation_mode",
        device_class=SensorDeviceClass.ENUM,
        options=_enum_options(OperationMode),
        value=lambda c: _lower(c.data.operation_mode),
    ),
    VorTechSensorDescription(
        key="operation_state",
        translation_key="operation_state",
        device_class=SensorDeviceClass.ENUM,
        options=_enum_options(OperationState),
        value=lambda c: _lower(c.data.operation_state),
    ),
    VorTechSensorDescription(
        key="active_scene",
        translation_key="active_scene",
        value=lambda c: c.data.scene_name(c.data.scene_id) or "Schedule",
    ),
    VorTechSensorDescription(
        key="scene_time_left",
        translation_key="scene_time_left",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value=_scene_remaining,
    ),
    VorTechSensorDescription(
        key="error",
        translation_key="error",
        device_class=SensorDeviceClass.ENUM,
        options=_enum_options(ErrorState),
        value=lambda c: _lower(c.data.error_state) or "noerror",
    ),
    # ---- running totals (daily/weekly/monthly figures in statistics) ---------------
    VorTechSensorDescription(
        key="run_time",
        translation_key="run_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value=lambda c: round(c.stats["run_seconds"] / 3600, 4),
    ),
    VorTechSensorDescription(
        key="off_time",
        translation_key="off_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value=lambda c: round(c.stats["off_seconds"] / 3600, 4),
    ),
    VorTechSensorDescription(
        key="energy",
        translation_key="energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
        value=lambda c: round(c.stats["energy_wh"] / 1000, 5),
        exists=lambda c: c.data.power_watts is not None,
    ),
    VorTechSensorDescription(
        key="water_moved",
        translation_key="water_moved",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        suggested_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value=lambda c: round(c.stats["pumped_litres"], 1),
        exists=lambda c: c.data.telemetry.get("gph_reliable", False),
    ),
    VorTechSensorDescription(
        key="feeds",
        translation_key="feeds",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value=lambda c: int(c.stats.get("feeds", 0)),
    ),
    VorTechSensorDescription(
        key="last_feed",
        translation_key="last_feed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=_last_feed,
    ),
    # ---- diagnostics ----------------------------------------------------------------
    VorTechSensorDescription(
        key="signal_strength",
        translation_key="signal_strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda c: c.link.connect_rssi if c.link.is_connected and c.link.connect_rssi else c.rssi,
    ),
    VorTechSensorDescription(
        key="bluetooth_link",
        translation_key="bluetooth_link",
        device_class=SensorDeviceClass.ENUM,
        options=["connected", "on_demand", "released", "disconnected"],
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda c: c.link_state,
        attrs=lambda c: {
            "address": c.link.address,
            "connected_through": c.link.connect_source,
            "connections_made": c.link.connect_count,
            "released_until": (
                dt_util.utc_from_timestamp(c.link.released_until).isoformat()
                if c.link.released_until
                else None
            ),
            "last_error": c.link.last_error,
        },
    ),
    VorTechSensorDescription(
        key="last_reading",
        translation_key="last_reading",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda c: dt_util.utc_from_timestamp(c.data.polled_at),
    ),
    VorTechSensorDescription(
        key="clock_drift",
        translation_key="clock_drift",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda c: c.data.clock_drift_seconds,
        attrs=lambda c: {
            "pump_time_zone": c.data.poll.metadata.olson_tz,
            "last_set_by_home_assistant": c.last_time_sync.isoformat() if c.last_time_sync else None,
        },
    ),
    VorTechSensorDescription(
        key="rated_max_flow",
        translation_key="rated_max_flow",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.GALLONS_PER_HOUR,
        suggested_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_HOUR,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda c: c.data.max_flow_gph,
        exists=lambda c: c.data.max_flow_gph is not None,
    ),
    VorTechSensorDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda c: c.data.main_firmware,
        attrs=lambda c: {**c.data.firmware_versions, **{
            f"hardware_{k.lower()}": v for k, v in (c.data.poll.metadata.hardware_info or {}).items()
        }},
    ),
    VorTechSensorDescription(
        key="pump_readings",
        translation_key="pump_readings",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda c: len(c.data.extra_values),
        attrs=lambda c: {
            k: (v if isinstance(v, (int, float)) else bytes(v).hex()) for k, v in c.data.extra_values.items()
        },
    ),
)


def _extra(name: str) -> Callable[[VorTechCoordinator], Any]:
    return lambda c: c.data.extra_values.get(name)


def _has_extra(name: str) -> Callable[[VorTechCoordinator], bool]:
    return lambda c: isinstance(c.data.extra_values.get(name), (int, float))


# Readings the pump reports besides speed, flow and power (PhysicalValues).
EXTRA_SENSORS: tuple[VorTechSensorDescription, ...] = (
    VorTechSensorDescription(
        key="driver_temperature",
        translation_key="driver_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value=_extra("DriverTemperature"),
        exists=_has_extra("DriverTemperature"),
    ),
    VorTechSensorDescription(
        key="motor_temperature",
        translation_key="motor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value=_extra("MotorTemperature"),
        exists=_has_extra("MotorTemperature"),
    ),
    VorTechSensorDescription(
        key="motor_rpm",
        translation_key="motor_rpm",
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        value=_extra("MotorRPM"),
        exists=_has_extra("MotorRPM"),
    ),
    VorTechSensorDescription(
        key="input_voltage",
        translation_key="input_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_extra("InputVoltage"),
        exists=_has_extra("InputVoltage"),
    ),
    VorTechSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value=_extra("BatteryVoltage"),
        exists=_has_extra("BatteryVoltage"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: VorTechConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        VorTechSensor(coordinator, description)
        for description in (*SENSORS, *EXTRA_SENSORS)
        if description.exists(coordinator)
    )


class VorTechSensor(VorTechEntity, SensorEntity):
    entity_description: VorTechSensorDescription

    def __init__(self, coordinator: VorTechCoordinator, description: VorTechSensorDescription) -> None:
        self.entity_description = description
        super().__init__(coordinator, description.key)

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value(self.coordinator)
        options = self.entity_description.options
        if options is not None and value not in options:
            return None  # a value this version doesn't know yet
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = self.entity_description.attrs
        return attrs(self.coordinator) if attrs else None
