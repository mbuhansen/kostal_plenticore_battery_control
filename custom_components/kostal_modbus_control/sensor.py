from __future__ import annotations

import logging
from typing import Optional

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
    UnitOfElectricCurrent,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    DOMAIN,
    REG_BATTERY_SOC,
    REG_BATTERY_POWER,
    REG_BATTERY_VOLTAGE,
    REG_BATTERY_CURRENT,
    REG_BATTERY_TEMP,
    REG_BATTERY_MAX_CHARGE_LIMIT,
    REG_BATTERY_MAX_DISCHARGE_LIMIT,
    SENSOR_BATTERY_SOC,
    SENSOR_BATTERY_POWER,
    SENSOR_BATTERY_VOLTAGE,
    SENSOR_BATTERY_CURRENT,
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
    
    entities = [
        KostalBatterySoCSensor(data, entry.entry_id),
        KostalBatteryPowerSensor(data, entry.entry_id),
        KostalBatteryVoltageSensor(data, entry.entry_id),
        KostalBatteryCurrentSensor(data, entry.entry_id),
        KostalBatteryTempSensor(data, entry.entry_id),
        KostalBatteryMaxChargeLimitSensor(data, entry.entry_id),
        KostalBatteryMaxDischargeLimitSensor(data, entry.entry_id),
    ]
    
    async_add_entities(entities)

class KostalBaseSensor(SensorEntity):
    """Base class for Kostal sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = True  # Enable polling for updates

    def __init__(self, data, entry_id):
        self._data = data
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_name = self._name

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
        )

    async def async_update(self) -> None:
        """Update the sensor."""
        val = await self._data.handler.read_float(self._address)
        if val is not None:
            self._attr_native_value = round(val, 2)
            self._attr_available = True
            self._update_data_store(val)
        else:
            self._attr_available = False
            
    def _update_data_store(self, val):
        pass

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

class KostalBatteryVoltageSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_VOLTAGE
    _name = "Battery Voltage"
    _address = REG_BATTERY_VOLTAGE
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT

class KostalBatteryCurrentSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_CURRENT
    _name = "Battery Current"
    _address = REG_BATTERY_CURRENT
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
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
    
    def _update_data_store(self, val):
        self._data.current_max_charge_watts = val

class KostalBatteryMaxDischargeLimitSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_MAX_DISCHARGE_LIMIT
    _name = "Battery Max Discharge Limit"
    _address = REG_BATTERY_MAX_DISCHARGE_LIMIT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def _update_data_store(self, val):
        self._data.current_max_discharge_watts = val
