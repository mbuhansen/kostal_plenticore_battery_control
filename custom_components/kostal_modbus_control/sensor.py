from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPower,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import KostalCoordinator
from .const import (
    DOMAIN,
    REG_BATTERY_SOC,
    REG_BATTERY_POWER,
    REG_BATTERY_VOLTAGE,
    REG_BATTERY_TEMP,
    REG_BATTERY_MAX_CHARGE_LIMIT,
    REG_BATTERY_MAX_DISCHARGE_LIMIT,
    SENSOR_BATTERY_SOC,
    SENSOR_BATTERY_POWER,
    SENSOR_BATTERY_VOLTAGE,
    SENSOR_BATTERY_TEMP,
    SENSOR_BATTERY_MAX_CHARGE_LIMIT,
    SENSOR_BATTERY_MAX_DISCHARGE_LIMIT,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Kostal Modbus sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.coordinator

    entities = [
        KostalBatterySoCSensor(coordinator, entry.entry_id),
        KostalBatteryPowerSensor(coordinator, entry.entry_id),
        KostalBatteryVoltageSensor(coordinator, entry.entry_id),
        KostalBatteryTempSensor(coordinator, entry.entry_id),
        KostalBatteryMaxChargeLimitSensor(coordinator, entry.entry_id),
        KostalBatteryMaxDischargeLimitSensor(coordinator, entry.entry_id),
    ]

    async_add_entities(entities)

class KostalBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Kostal sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KostalCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_name = self._name

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
        )

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get(self._address)
        return round(val, 2) if val is not None else None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.data is not None

class KostalBatterySoCSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_SOC
    _name = "Battery SoC"
    _address = REG_BATTERY_SOC
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

class KostalBatteryPowerSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_POWER
    _name = "Battery Power"
    _address = REG_BATTERY_POWER
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get(self._address)
        return int(val) if val is not None else None


class KostalBatteryVoltageSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_VOLTAGE
    _name = "Battery Voltage"
    _address = REG_BATTERY_VOLTAGE
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT


class KostalBatteryTempSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_TEMP
    _name = "Battery Temperature"
    _address = REG_BATTERY_TEMP
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

class KostalBatteryMaxChargeLimitSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_MAX_CHARGE_LIMIT
    _name = "Battery Max Charge Limit"
    _address = REG_BATTERY_MAX_CHARGE_LIMIT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT


class KostalBatteryMaxDischargeLimitSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_MAX_DISCHARGE_LIMIT
    _name = "Battery Max Discharge Limit"
    _address = REG_BATTERY_MAX_DISCHARGE_LIMIT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
