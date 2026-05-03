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
    UnitOfElectricCurrent,
    UnitOfTemperature,
    UnitOfEnergy,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import KostalCoordinator
from .const import (
    CONF_INVERTER_TYPE,
    DOMAIN,
    INVERTER_TYPE_BI,
    INVERTER_TYPE_HYBRID,
    REG_INVERTER_STATE,
    REG_TOTAL_ACTIVE_POWER,
    REG_VOLTAGE_PHASE1,
    REG_VOLTAGE_PHASE2,
    REG_VOLTAGE_PHASE3,
    REG_BATTERY_SOC,
    REG_BATTERY_POWER,
    REG_BATTERY_VOLTAGE,
    REG_BATTERY_TEMP,
    REG_BATTERY_MAX_CHARGE_LIMIT,
    REG_BATTERY_MAX_DISCHARGE_LIMIT,
    REG_CHARGE_DISCHARGE_LIMIT,
    REG_CHARGE_DISCHARGE_LIMIT_BI,
    REG_CHARGE_RATE,
    REG_DISCHARGE_RATE,
    REG_BATTERY_WORK_CAPACITY,
    REG_BATTERY_MGMT_MODE,
    REG_BATTERY_TYPE,
    REG_BATTERY_CHARGE_CURRENT,
    REG_BATTERY_CYCLES,
    REG_BATTERY_GROSS_CAPACITY,
    REG_BATTERY_MODEL_ID,
    REG_BATTERY_BMS_SERIAL,
    REG_BATTERY_FIRMWARE,
    REG_BATTERY_MIN_SOC,
    REG_BATTERY_MAX_SOC,
    REG_CURRENT_PHASE1,
    REG_CURRENT_PHASE2,
    REG_CURRENT_PHASE3,
    REG_SENSOR_TYPE,
    SENSOR_TOTAL_ACTIVE_POWER,
    SENSOR_VOLTAGE_PHASE1,
    SENSOR_VOLTAGE_PHASE2,
    SENSOR_VOLTAGE_PHASE3,
    SENSOR_BATTERY_SOC,
    SENSOR_BATTERY_POWER,
    SENSOR_BATTERY_VOLTAGE,
    SENSOR_BATTERY_TEMP,
    SENSOR_BATTERY_MAX_CHARGE_LIMIT,
    SENSOR_BATTERY_MAX_DISCHARGE_LIMIT,
    SENSOR_CURRENT_PHASE1,
    SENSOR_CURRENT_PHASE2,
    SENSOR_CURRENT_PHASE3,
    SENSOR_SENSOR_TYPE,
    SENSOR_EMS_STATUS,
    SENSOR_EMS_CHARGE_LIMIT,
    SENSOR_PREDBAT_STATUS,
    SENSOR_BATTERY_CHARGE_CURRENT_SETPOINT,
    SENSOR_BATTERY_CHARGE_POWER_SETPOINT,
    SENSOR_BATTERY_MAX_CHARGE_POWER_LIMIT,
    SENSOR_BATTERY_MAX_DISCHARGE_POWER_LIMIT,
    SENSOR_BATTERY_WORK_CAPACITY,
    SENSOR_BATTERY_MGMT_MODE,
    SENSOR_BATTERY_TYPE,
    SENSOR_BATTERY_FIRMWARE,
    SENSOR_BATTERY_BMS_SERIAL,
    SENSOR_BATTERY_MODEL_ID,
    SENSOR_BATTERY_GROSS_CAPACITY,
    SENSOR_BATTERY_CYCLES,
    SENSOR_BATTERY_CHARGE_CURRENT,
    SENSOR_BATTERY_MIN_SOC,
    SENSOR_BATTERY_MAX_SOC,
    BATTERY_TYPE_MAP,
    INVERTER_STATE_MAP,
    SENSOR_INVERTER_STATE,
    SENSOR_INVERTER_STATE_TEXT,
    SENSOR_TYPE_MAP,
    SIGNAL_EMS_STATUS_UPDATED,
    SIGNAL_PREDBAT_STATUS_UPDATED,
    SENSOR_PREDBAT_MODE,
    PREDBAT_MODE_ENTITY,
    PREDBAT_ACTIVE_MODES,
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
    inverter_type = entry.data.get(CONF_INVERTER_TYPE, INVERTER_TYPE_HYBRID)

    entities = [
        KostalTotalActivePowerSensor(coordinator, entry.entry_id),
        KostalBatterySoCSensor(coordinator, entry.entry_id),
        KostalBatteryPowerSensor(coordinator, entry.entry_id),
        KostalBatteryVoltageSensor(coordinator, entry.entry_id),
        KostalBatteryTempSensor(coordinator, entry.entry_id),
        KostalBatteryMaxChargeLimitSensor(coordinator, entry.entry_id),
        KostalBatteryMaxDischargeLimitSensor(coordinator, entry.entry_id),
        KostalVoltagePhase1Sensor(coordinator, entry.entry_id),
        KostalVoltagePhase2Sensor(coordinator, entry.entry_id),
        KostalVoltagePhase3Sensor(coordinator, entry.entry_id),
        KostalCurrentPhase1Sensor(coordinator, entry.entry_id),
        KostalCurrentPhase2Sensor(coordinator, entry.entry_id),
        KostalCurrentPhase3Sensor(coordinator, entry.entry_id),
        KostalSensorTypeSensor(coordinator, entry.entry_id),
        KostalEMSStatusSensor(data, entry.entry_id),
        KostalEMSChargeLimitSensor(data, entry.entry_id),
        KostalPredbatStatusSensor(data, entry.entry_id),
        KostalPredbatModeSensor(data, entry.entry_id),
        # Diagnostic sensors (disabled by default)
        KostalInverterStateSensor(coordinator, entry.entry_id),
        KostalInverterStateTextSensor(coordinator, entry.entry_id),
        KostalBatteryWorkCapacitySensor(coordinator, entry.entry_id),
        KostalBatteryMgmtModeSensor(coordinator, entry.entry_id),
        # Diagnostic sensors (enabled by default)
        KostalBatteryTypeSensor(coordinator, entry.entry_id),
        # Diagnostic sensors (disabled by default) - extended battery info
        KostalBatteryFirmwareSensor(coordinator, entry.entry_id),
        KostalBatteryBmsSerialSensor(coordinator, entry.entry_id),
        KostalBatteryModelIdSensor(coordinator, entry.entry_id),
        KostalBatteryGrossCapacitySensor(coordinator, entry.entry_id),
        KostalBatteryCyclesSensor(coordinator, entry.entry_id),
        KostalBatteryChargeCurrentSensor(coordinator, entry.entry_id),
        KostalBatteryMaxChargePowerLimitSensor(coordinator, entry.entry_id),
        KostalBatteryMaxDischargePowerLimitSensor(coordinator, entry.entry_id),
        # SOC limit sensors (diagnostic, disabled by default)
        KostalBatteryMinSoCSensor(coordinator, entry.entry_id),
        KostalBatteryMaxSoCSensor(coordinator, entry.entry_id),
    ]

    if inverter_type == INVERTER_TYPE_BI:
        entities.append(KostalBatteryChargePowerSetpointSensor(coordinator, entry.entry_id))
    else:
        entities.append(KostalBatteryChargeCurrentSetpointSensor(coordinator, entry.entry_id))

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


class KostalTotalActivePowerSensor(KostalBaseSensor):
    _key = SENSOR_TOTAL_ACTIVE_POWER
    _name = "Grid Power"
    _address = REG_TOTAL_ACTIVE_POWER
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT


class KostalBatteryChargeCurrentSetpointSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_CHARGE_CURRENT_SETPOINT
    _name = "Battery Charge Current Setpoint"
    _address = REG_CHARGE_DISCHARGE_LIMIT
    _attr_device_class = None
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class KostalBatteryChargePowerSetpointSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_CHARGE_POWER_SETPOINT
    _name = "Battery Charge Power Setpoint"
    _address = REG_CHARGE_DISCHARGE_LIMIT_BI
    _attr_device_class = None
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class KostalBatteryMaxChargePowerLimitSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_MAX_CHARGE_POWER_LIMIT
    _name = "Battery Max Charge Power Setpoint"
    _address = REG_CHARGE_RATE
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class KostalBatteryMaxDischargePowerLimitSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_MAX_DISCHARGE_POWER_LIMIT
    _name = "Battery Max Discharge Power Setpoint"
    _address = REG_DISCHARGE_RATE
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

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
    _name = "Battery Max Charge Power Limit Read-out"
    _address = REG_BATTERY_MAX_CHARGE_LIMIT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT


class KostalBatteryMaxDischargeLimitSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_MAX_DISCHARGE_LIMIT
    _name = "Battery Max Discharge Power Limit Read-out"
    _address = REG_BATTERY_MAX_DISCHARGE_LIMIT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT


class KostalCurrentPhase1Sensor(KostalBaseSensor):
    _key = SENSOR_CURRENT_PHASE1
    _name = "Grid Current Phase 1"
    _address = REG_CURRENT_PHASE1
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT


class KostalCurrentPhase2Sensor(KostalBaseSensor):
    _key = SENSOR_CURRENT_PHASE2
    _name = "Grid Current Phase 2"
    _address = REG_CURRENT_PHASE2
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT


class KostalCurrentPhase3Sensor(KostalBaseSensor):
    _key = SENSOR_CURRENT_PHASE3
    _name = "Grid Current Phase 3"
    _address = REG_CURRENT_PHASE3
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT


class KostalVoltagePhase1Sensor(KostalBaseSensor):
    _key = SENSOR_VOLTAGE_PHASE1
    _name = "Grid Voltage Phase 1"
    _address = REG_VOLTAGE_PHASE1
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class KostalVoltagePhase2Sensor(KostalBaseSensor):
    _key = SENSOR_VOLTAGE_PHASE2
    _name = "Grid Voltage Phase 2"
    _address = REG_VOLTAGE_PHASE2
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class KostalVoltagePhase3Sensor(KostalBaseSensor):
    _key = SENSOR_VOLTAGE_PHASE3
    _name = "Grid Voltage Phase 3"
    _address = REG_VOLTAGE_PHASE3
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class KostalSensorTypeSensor(KostalBaseSensor):
    _key = SENSOR_SENSOR_TYPE
    _name = "Smart Meter Type"
    _address = REG_SENSOR_TYPE
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_state_class = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get(self._address)
        if val is None:
            return None
        return SENSOR_TYPE_MAP.get(val, f"Unknown (0x{val:02X})")


class KostalEMSStatusSensor(SensorEntity):
    """Sensor showing the current EMS Grid Protection status."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["Inactive", "Ok", "Protecting", "Blocked"]
    _attr_icon = "mdi:shield-check"

    def __init__(self, data, entry_id: str) -> None:
        self._data = data
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{SENSOR_EMS_STATUS}"
        self._attr_name = "EMS Grid Protection Status"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)})

    @property
    def native_value(self) -> str:
        return self._data.ems_status

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_EMS_STATUS_UPDATED}_{self._entry_id}",
                self._handle_status_update,
            )
        )

    @callback
    def _handle_status_update(self, status: str) -> None:
        self.async_write_ha_state()


class KostalEMSChargeLimitSensor(SensorEntity):
    """Sensor showing the charge limit calculated by EMS."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.POWER_FACTOR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:lightning-bolt"

    def __init__(self, data, entry_id: str) -> None:
        self._data = data
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{SENSOR_EMS_CHARGE_LIMIT}"
        self._attr_name = "EMS Charge Limit"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)})

    @property
    def native_value(self) -> float | None:
        if self._data.ems_status == "Inactive":
            return None
        return round(self._data.ems_charge_limit_pct, 1)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_EMS_STATUS_UPDATED}_{self._entry_id}",
                self._handle_status_update,
            )
        )

    @callback
    def _handle_status_update(self, status: str) -> None:
        self.async_write_ha_state()


class KostalPredbatStatusSensor(SensorEntity):
    """Sensor showing the current Predbat decision while Charge Start is active."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["Inactive", "Waiting", "Charge", "Hold", "Hold for car"]
    _attr_icon = "mdi:home-battery"

    def __init__(self, data, entry_id: str) -> None:
        self._data = data
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{SENSOR_PREDBAT_STATUS}"
        self._attr_name = "Predbat Status"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)})

    @property
    def native_value(self) -> str:
        return self._data.predbat_status

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_PREDBAT_STATUS_UPDATED}_{self._entry_id}",
                self._handle_status_update,
            )
        )

    @callback
    def _handle_status_update(self, status: str) -> None:
        self.async_write_ha_state()


class KostalPredbatModeSensor(SensorEntity):
    """Sensor showing whether Predbat is installed and in an active control mode."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["Not installed", "Disabled", "Enabled"]
    _attr_icon = "mdi:home-battery-outline"

    def __init__(self, data, entry_id: str) -> None:
        self._data = data
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{SENSOR_PREDBAT_MODE}"
        self._attr_name = "Predbat Mode"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)})

    @property
    def native_value(self) -> str:
        state = self.hass.states.get(PREDBAT_MODE_ENTITY)
        if state is None:
            return "Not installed"
        if state.state in PREDBAT_ACTIVE_MODES:
            return "Enabled"
        return "Disabled"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [PREDBAT_MODE_ENTITY],
                self._handle_predbat_mode_change,
            )
        )

    @callback
    def _handle_predbat_mode_change(self, event) -> None:
        self.async_write_ha_state()


class KostalInverterStateSensor(KostalBaseSensor):
    _key = SENSOR_INVERTER_STATE
    _name = "Inverter State"
    _address = REG_INVERTER_STATE
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class KostalInverterStateTextSensor(KostalBaseSensor):
    _key = SENSOR_INVERTER_STATE_TEXT
    _name = "Inverter State Text"
    _address = REG_INVERTER_STATE
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_state_class = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get(self._address)
        if val is None:
            return None
        return INVERTER_STATE_MAP.get(val, f"Unknown ({val})")


class KostalBatteryWorkCapacitySensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_WORK_CAPACITY
    _name = "Battery Work Capacity"
    _address = REG_BATTERY_WORK_CAPACITY
    _attr_device_class = SensorDeviceClass.ENERGY_STORAGE
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class KostalBatteryMgmtModeSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_MGMT_MODE
    _name = "Battery Management Mode"
    _address = REG_BATTERY_MGMT_MODE
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_state_class = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._address)


class KostalBatteryTypeSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_TYPE
    _name = "Battery Type"
    _address = REG_BATTERY_TYPE
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_state_class = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get(self._address)
        if val is None:
            return None
        return BATTERY_TYPE_MAP.get(val, f"Unknown (0x{val:04X})")


class KostalBatteryFirmwareSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_FIRMWARE
    _name = "Battery Firmware"
    _address = REG_BATTERY_FIRMWARE
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_state_class = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get(self._address)
        return f"0x{val:08X}" if val is not None else None


class KostalBatteryBmsSerialSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_BMS_SERIAL
    _name = "Battery BMS Serial Number"
    _address = REG_BATTERY_BMS_SERIAL
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_state_class = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get(self._address)
        return str(val) if val is not None else None


class KostalBatteryModelIdSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_MODEL_ID
    _name = "Battery Model ID"
    _address = REG_BATTERY_MODEL_ID
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_state_class = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get(self._address)
        return str(val) if val is not None else None


class KostalBatteryGrossCapacitySensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_GROSS_CAPACITY
    _name = "Battery Gross Capacity"
    _address = REG_BATTERY_GROSS_CAPACITY
    _attr_device_class = None
    _attr_native_unit_of_measurement = "Ah"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class KostalBatteryCyclesSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_CYCLES
    _name = "Battery Cycles"
    _address = REG_BATTERY_CYCLES
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class KostalBatteryChargeCurrentSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_CHARGE_CURRENT
    _name = "Battery Charge Current"
    _address = REG_BATTERY_CHARGE_CURRENT
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class KostalBatteryMinSoCSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_MIN_SOC
    _name = "Battery Minimum SOC"
    _address = REG_BATTERY_MIN_SOC
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False


class KostalBatteryMaxSoCSensor(KostalBaseSensor):
    _key = SENSOR_BATTERY_MAX_SOC
    _name = "Battery Maximum SOC"
    _address = REG_BATTERY_MAX_SOC
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
