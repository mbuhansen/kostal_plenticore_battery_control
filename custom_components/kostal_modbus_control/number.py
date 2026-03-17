from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    DOMAIN,
    NUMBER_CHARGE_RATE,
    NUMBER_DISCHARGE_RATE,
    DEFAULT_CHARGE_RATE,
    DEFAULT_DISCHARGE_RATE,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Kostal Modbus numbers."""
    data = hass.data[DOMAIN][entry.entry_id]
    
    # Use current data values as defaults (initialized from battery limits in __init__)
    entities = [
        KostalNumber(data, entry.entry_id, NUMBER_CHARGE_RATE, "Set Charge Rate", data.charge_rate, "W"),
        KostalNumber(data, entry.entry_id, NUMBER_DISCHARGE_RATE, "Set Discharge Rate", data.discharge_rate, "W"),
    ]
    
    async_add_entities(entities)

class KostalNumber(RestoreNumber):
    """Representation of a Kostal Modbus Number."""

    _attr_has_entity_name = True
    _attr_native_min_value = 0.0
    _attr_native_max_value = 15000.0
    _attr_native_step = 50.0

    def __init__(self, data, entry_id, key, name, default, unit):
        self._data = data
        self._entry_id = entry_id
        self._key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_name = name
        self._attr_native_value = default
        self._attr_native_unit_of_measurement = unit
        self._attr_mode = "box"
        
        # Initialize data store with default initially
        self._update_data_store(default)
        
    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_number_data()) is not None and state.native_value is not None:
             self._attr_native_value = state.native_value
             self._update_data_store(state.native_value)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
        )

    def _update_data_store(self, value):
        """Update the shared data object."""
        if self._key == NUMBER_CHARGE_RATE:
            self._data.charge_rate = value
        elif self._key == NUMBER_DISCHARGE_RATE:
            self._data.discharge_rate = value

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        self._attr_native_value = value
        self._update_data_store(value)
        self.async_write_ha_state()

