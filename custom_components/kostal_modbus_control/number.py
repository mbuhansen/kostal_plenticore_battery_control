from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import (
    DOMAIN,
    NUMBER_CHARGE_RATE,
    NUMBER_DISCHARGE_RATE,
    NUMBER_FUSE_SIZE,
    NUMBER_BATTERY_MAX_CURRENT,
    DEFAULT_CHARGE_RATE,
    DEFAULT_DISCHARGE_RATE,
    DEFAULT_FUSE_SIZE,
    DEFAULT_BATTERY_MAX_CURRENT,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Kostal Modbus numbers."""
    data = hass.data[DOMAIN][entry.entry_id]

    entities = [
        KostalNumber(data, entry.entry_id, NUMBER_CHARGE_RATE, "Set Charge Rate", "%", DEFAULT_CHARGE_RATE),
        KostalNumber(data, entry.entry_id, NUMBER_DISCHARGE_RATE, "Set Discharge Rate", "%", DEFAULT_DISCHARGE_RATE),
        KostalFuseSizeNumber(data, entry.entry_id),
        KostalBatteryMaxCurrentNumber(data, entry.entry_id),
    ]

    async_add_entities(entities)

class KostalNumber(RestoreNumber):
    """Representation of a Kostal Modbus Number."""

    _attr_has_entity_name = True
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_mode = "box"

    def __init__(self, data, entry_id, key, name, unit, default):
        self._data = data
        self._entry_id = entry_id
        self._key = key
        self._default = default
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_name = name
        self._attr_native_value = default
        self._attr_native_unit_of_measurement = unit
        self._update_data_store(default)

    async def async_added_to_hass(self) -> None:
        """Restore last user-set value on HA restart."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_number_data()) is not None and state.native_value is not None:
            self._attr_native_value = state.native_value
            self._update_data_store(state.native_value)
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
        )

    def _update_data_store(self, value):
        if self._key == NUMBER_CHARGE_RATE:
            self._data.charge_rate = value
        elif self._key == NUMBER_DISCHARGE_RATE:
            self._data.discharge_rate = value

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._update_data_store(value)
        self.async_write_ha_state()


class KostalFuseSizeNumber(RestoreNumber):
    """Input for house fuse size in Ampere."""

    _attr_has_entity_name = True
    _attr_unique_id = None  # Set in __init__
    _attr_native_min_value = 6.0
    _attr_native_max_value = 125.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "A"
    _attr_mode = "box"
    _attr_name = "House Fuse Size"
    _attr_icon = "mdi:fuse"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, data, entry_id: str) -> None:
        self._data = data
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{NUMBER_FUSE_SIZE}"
        self._attr_native_value = DEFAULT_FUSE_SIZE
        self._data.fuse_size = DEFAULT_FUSE_SIZE

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (state := await self.async_get_last_number_data()) is not None and state.native_value is not None:
            self._attr_native_value = state.native_value
            self._data.fuse_size = float(state.native_value)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._data.fuse_size = value
        self.async_write_ha_state()

        self._update_data_store(value)
        self.async_write_ha_state()


class KostalBatteryMaxCurrentNumber(RestoreNumber):
    """Input for battery max DC current in Ampere."""

    _attr_has_entity_name = True
    _attr_native_min_value = 13.0
    _attr_native_max_value = 50.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "A"
    _attr_mode = "box"
    _attr_name = "Battery Max Current"
    _attr_icon = "mdi:current-dc"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, data, entry_id: str) -> None:
        self._data = data
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{NUMBER_BATTERY_MAX_CURRENT}"
        self._attr_native_value = DEFAULT_BATTERY_MAX_CURRENT
        self._data.battery_max_current = DEFAULT_BATTERY_MAX_CURRENT

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (state := await self.async_get_last_number_data()) is not None and state.native_value is not None:
            self._attr_native_value = state.native_value
            self._data.battery_max_current = float(state.native_value)

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self._data.battery_max_current = value
        self.async_write_ha_state()
