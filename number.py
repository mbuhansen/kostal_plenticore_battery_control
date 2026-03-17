from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    DOMAIN,
    NUMBER_CHARGE_RATE,
    NUMBER_DISCHARGE_RATE,
    NUMBER_MAX_CHARGE_PERCENT,
    NUMBER_MAX_DISCHARGE_PERCENT,
    DEFAULT_CHARGE_RATE,
    DEFAULT_DISCHARGE_RATE,
    DEFAULT_MAX_PERCENT,
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
        KostalNumber(data, entry.entry_id, NUMBER_MAX_CHARGE_PERCENT, "Max Charge Percent", DEFAULT_MAX_PERCENT, "%"),
        KostalNumber(data, entry.entry_id, NUMBER_MAX_DISCHARGE_PERCENT, "Max Discharge Percent", DEFAULT_MAX_PERCENT, "%"),
        KostalNumber(data, entry.entry_id, NUMBER_CHARGE_RATE, "Charge Rate", DEFAULT_CHARGE_RATE, "W"),
        KostalNumber(data, entry.entry_id, NUMBER_DISCHARGE_RATE, "Discharge Rate", DEFAULT_DISCHARGE_RATE, "W"),
    ]
    
    async_add_entities(entities)

class KostalNumber(NumberEntity):
    """Representation of a Kostal Modbus Number."""

    _attr_has_entity_name = True

    def __init__(self, data, entry_id, key, name, default, unit):
        self._data = data
        self._entry_id = entry_id
        self._key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_name = name
        self._attr_native_value = default
        self._attr_native_unit_of_measurement = unit
        self._attr_mode = "box"
        
        # Initialize data store
        self._update_data_store(default)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
        )

    def _update_data_store(self, value):
        """Update the shared data object."""
        if self._key == NUMBER_MAX_CHARGE_PERCENT:
            self._data.max_charge_percent = value
        elif self._key == NUMBER_MAX_DISCHARGE_PERCENT:
            self._data.max_discharge_percent = value
        elif self._key == NUMBER_CHARGE_RATE:
            self._data.charge_rate = value
        elif self._key == NUMBER_DISCHARGE_RATE:
            self._data.discharge_rate = value

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        self._attr_native_value = value
        self._update_data_store(value)
        self.async_write_ha_state()

