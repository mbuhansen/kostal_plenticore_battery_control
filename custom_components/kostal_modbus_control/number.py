from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import KostalCoordinator
from .const import (
    DOMAIN,
    NUMBER_CHARGE_RATE,
    NUMBER_DISCHARGE_RATE,
    NUMBER_FUSE_SIZE,
    DEFAULT_CHARGE_RATE,
    DEFAULT_DISCHARGE_RATE,
    DEFAULT_FUSE_SIZE,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Kostal Modbus numbers."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data.coordinator

    entities = [
        KostalNumber(coordinator, data, entry.entry_id, NUMBER_CHARGE_RATE, "Set Charge Rate", "W"),
        KostalNumber(coordinator, data, entry.entry_id, NUMBER_DISCHARGE_RATE, "Set Discharge Rate", "W"),
        KostalFuseSizeNumber(data, entry.entry_id),
    ]

    async_add_entities(entities)

class KostalNumber(CoordinatorEntity, RestoreNumber):
    """Representation of a Kostal Modbus Number."""

    _attr_has_entity_name = True
    _attr_native_min_value = 0.0
    _attr_native_max_value = 15000.0
    _attr_native_step = 50.0
    _attr_mode = "box"
    _restored = False

    def __init__(self, coordinator: KostalCoordinator, data, entry_id, key, name, unit):
        CoordinatorEntity.__init__(self, coordinator)
        self._data = data
        self._entry_id = entry_id
        self._key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_name = name
        self._attr_native_value = None
        self._attr_native_unit_of_measurement = unit

    async def async_added_to_hass(self) -> None:
        """Restore last state, then listen for coordinator updates."""
        await super().async_added_to_hass()
        if (state := await self.async_get_last_number_data()) is not None and state.native_value is not None:
            self._attr_native_value = state.native_value
            self._update_data_store(state.native_value)
            self._restored = True

    @callback
    def _handle_coordinator_update(self) -> None:
        """On first coordinator update, seed value from inverter max limits if not restored."""
        if not self._restored and self.coordinator.data is not None:
            if self._key == NUMBER_CHARGE_RATE:
                val = self._data.current_max_charge_watts
            else:
                val = self._data.current_max_discharge_watts
            if val and val > 0:
                self._attr_native_value = val
                self._update_data_store(val)
                self._restored = True
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

