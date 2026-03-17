from __future__ import annotations

import logging
import asyncio
import time
from datetime import timedelta
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    DOMAIN,
    LOOP_INTERVAL,
    REG_CHARGE_DISCHARGE_LIMIT,
    REG_CHARGE_RATE,
    REG_CHARGE_RATE_ALT,
    REG_DISCHARGE_RATE,
    SWITCH_BLOCK_CHARGE,
    SWITCH_CHARGE_START,
    SWITCH_BLOCK_DISCHARGE,
    SWITCH_DISCHARGE_START,
)
from .modbus_handler import KostalModbusHandler

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Kostal Modbus switches."""
    data = hass.data[DOMAIN][entry.entry_id]
    
    entities = [
        KostalChargeStartSwitch(data, entry.entry_id),
        KostalDischargeStartSwitch(data, entry.entry_id),
        KostalBlockDischargeSwitch(data, entry.entry_id),
        KostalBlockChargeSwitch(data, entry.entry_id),
    ]
    
    async_add_entities(entities)

class KostalBaseSwitch(SwitchEntity):
    """Base class for Kostal switches."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, data, entry_id):
        self._data = data
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_name = self._name
        self._remove_timer = None
        self._attr_is_on = False
        
        # Calculate derived timings
        # Loop interval = Inverter Timeout / 2 (send twice per timeout period)
        self._loop_interval = max(int(self._data.inverter_timeout / 2), 5)
        # Wait time = Inverter Timeout + X (e.g., 15s safety buffer)
        self._wait_time_before_start = self._data.inverter_timeout + 15.0

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        self._attr_is_on = True
        self.async_write_ha_state() # Update state immediately
        
        # Check wait time since last stop
        time_since_last_stop = time.time() - self._data.last_stop_time
        if time_since_last_stop < self._wait_time_before_start:
            sleep_duration = self._wait_time_before_start - time_since_last_stop
            _LOGGER.info(f"Waiting {sleep_duration:.1f}s before starting {self.name} (mandatory delay)")
            await asyncio.sleep(sleep_duration)

        # Run once immediately
        await self._loop_action()
        
        # Start timer
        self._remove_timer = async_track_time_interval(
            self.hass, self._loop_action, timedelta(seconds=self._loop_interval)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if self._remove_timer:
            self._remove_timer()
            self._remove_timer = None
        
        self._attr_is_on = False
        await self._stop_action()
        
        # Update stop time
        self._data.last_stop_time = time.time()
        
        self.async_write_ha_state()

    async def _loop_action(self, *args):
        """Action performed periodically."""
        pass

    async def _stop_action(self):
        """Action performed when stopping."""
        pass

class KostalChargeStartSwitch(KostalBaseSwitch):
    _key = SWITCH_CHARGE_START
    _name = "Charge Start"

    async def _loop_action(self, *args):
        # Write negative max charge percent to 1028
        val_limit = -abs(self._data.max_charge_percent)
        await self._data.handler.write_float(REG_CHARGE_DISCHARGE_LIMIT, val_limit)
        
        # Charge Start: No specific write to 1038 or 1040 needed unless specified.
        # But if we need to set max charge rate here? The automation used 1034 before.
        # Since you said 1038/1040 are for BLOCKING (0), we might not need to write to them here?
        # However, to be safe, if we want to ensure charging is ALLOWED, we might need to reset blocks?
        # For now, following ONLY the logic for 1028 as the primary control for forcing charge.

    async def _stop_action(self):
        # Write 0 stop charge
        await self._data.handler.write_float(REG_CHARGE_DISCHARGE_LIMIT, 0.0)

class KostalDischargeStartSwitch(KostalBaseSwitch):
    _key = SWITCH_DISCHARGE_START
    _name = "Discharge Start"

    async def _loop_action(self, *args):
        # Write positive max discharge percent to 1028
        val_limit = abs(self._data.max_discharge_percent)
        await self._data.handler.write_float(REG_CHARGE_DISCHARGE_LIMIT, val_limit)

    async def _stop_action(self):
        # Write 0 stop discharge
        await self._data.handler.write_float(REG_CHARGE_DISCHARGE_LIMIT, 0.0)

class KostalBlockDischargeSwitch(KostalBaseSwitch):
    _key = SWITCH_BLOCK_DISCHARGE
    _name = "Block Discharge"

    async def _loop_action(self, *args):
        # Write discharge rate 0 to Block Discharge (1040)
        # MUST BE POSITIVE (0 is positive)
        await self._data.handler.write_float(REG_DISCHARGE_RATE, 0.0)

    async def _stop_action(self):
        pass

class KostalBlockChargeSwitch(KostalBaseSwitch):
    _key = SWITCH_BLOCK_CHARGE
    _name = "Block Charge"

    async def _loop_action(self, *args):
        # Write 0 to charge rate (Block Charge) via 1038
        # MUST BE POSITIVE (0 is positive)
        await self._data.handler.write_float(REG_CHARGE_RATE, 0.0)

    async def _stop_action(self):
        pass
