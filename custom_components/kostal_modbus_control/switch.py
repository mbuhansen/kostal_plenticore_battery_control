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
    REG_POWER_LIMIT_W,
    REG_CHARGE_RATE,
    REG_DISCHARGE_RATE,
    REG_CURRENT_PHASE1,
    REG_CURRENT_PHASE2,
    REG_CURRENT_PHASE3,
    REG_SENSOR_TYPE,
    SWITCH_BLOCK_CHARGE,
    SWITCH_CHARGE_START,
    SWITCH_BLOCK_DISCHARGE,
    SWITCH_DISCHARGE_START,
    SWITCH_EMS,
    EMS_SAFETY_MARGIN,
    EMS_PHASE_VOLTAGE,
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
        KostalEMSSwitch(data, entry.entry_id),
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
        self._related_switches = []
        
        # Calculate derived timings
        # Loop interval = Inverter Timeout / 2 (send twice per timeout period)
        self._loop_interval = max(int(self._data.inverter_timeout / 2), 5)
        # Wait time = Inverter Timeout + X (e.g., 15s safety buffer)
        self._wait_time_before_start = self._data.inverter_timeout + 15.0

    def set_related_switches(self, switches):
        self._related_switches = switches

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        # Ensure mutually exclusive behavior
        for switch in self._related_switches:
            if switch is not self and switch.is_on:
                await switch.async_turn_off()

        self._attr_is_on = True
        self.async_write_ha_state()
        self.hass.async_create_task(self._start_loop())

    async def _start_loop(self) -> None:
        """Background task: wait if needed, then start the periodic loop."""
        time_since_last_stop = time.time() - self._data.last_stop_time
        if time_since_last_stop < self._wait_time_before_start:
            sleep_duration = self._wait_time_before_start - time_since_last_stop
            _LOGGER.info(f"Waiting {sleep_duration:.1f}s before starting {self.name} (mandatory delay)")
            await asyncio.sleep(sleep_duration)
            if not self._attr_is_on:
                return

        await self._loop_action()
        if self._attr_is_on:
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
        # User defined watts
        user_watts = self._data.charge_rate
        # Max limit from battery sensor
        max_limit = self._data.current_max_charge_watts
        
        # Clamp to max limit if available (greater than 0)
        target_watts = user_watts
        if max_limit > 0:
            target_watts = min(user_watts, max_limit)
        
        # Write negative target watts to 1034 (Charge)
        val_to_write = -abs(target_watts)
        await self._data.handler.write_float(REG_POWER_LIMIT_W, val_to_write)

    async def _stop_action(self):
        # Write 0 stop charge
        await self._data.handler.write_float(REG_POWER_LIMIT_W, 0.0)

class KostalDischargeStartSwitch(KostalBaseSwitch):
    _key = SWITCH_DISCHARGE_START
    _name = "Discharge Start"

    async def _loop_action(self, *args):
        # User defined watts
        user_watts = self._data.discharge_rate
        # Max limit from battery sensor
        max_limit = self._data.current_max_discharge_watts
        
        # Clamp to max limit if available (greater than 0)
        target_watts = user_watts
        if max_limit > 0:
            target_watts = min(user_watts, max_limit)

        # Write positive target watts to 1034 (Discharge)
        val_to_write = abs(target_watts)
        await self._data.handler.write_float(REG_POWER_LIMIT_W, val_to_write)

    async def _stop_action(self):
        # Write 0 stop discharge
        await self._data.handler.write_float(REG_POWER_LIMIT_W, 0.0)

class KostalBlockDischargeSwitch(KostalBaseSwitch):
    _key = SWITCH_BLOCK_DISCHARGE
    _name = "Block Discharge"

    async def _loop_action(self, *args):
        # Write discharge rate 0 to Block Discharge (1040)
        # MUST BE POSITIVE (0 is positive)
        await self._data.handler.write_float(REG_DISCHARGE_RATE, 0.0)

    async def _stop_action(self):
        # Restore user-configured discharge rate when unblocking
        await self._data.handler.write_float(REG_DISCHARGE_RATE, self._data.discharge_rate)

class KostalBlockChargeSwitch(KostalBaseSwitch):
    _key = SWITCH_BLOCK_CHARGE
    _name = "Block Charge"

    async def _loop_action(self, *args):
        # Write 0 to charge rate (Block Charge) via 1038
        # MUST BE POSITIVE (0 is positive)
        await self._data.handler.write_float(REG_CHARGE_RATE, 0.0)

    async def _stop_action(self):
        # Restore user-configured charge rate when unblocking
        await self._data.handler.write_float(REG_CHARGE_RATE, self._data.charge_rate)


class KostalEMSSwitch(KostalBaseSwitch):
    _key = SWITCH_EMS
    _name = "EMS Grid Protection"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on EMS — blocked if no smart meter is detected."""
        coordinator = self._data.coordinator
        if coordinator is None or coordinator.data is None:
            _LOGGER.warning("EMS: Cannot enable — no coordinator data available yet")
            return

        sensor_type = coordinator.data.get(REG_SENSOR_TYPE)
        if sensor_type is None or sensor_type == 0xFF:
            _LOGGER.warning(
                "EMS: Cannot enable — no smart meter detected (sensor_type=0x%02X)",
                sensor_type if sensor_type is not None else 0xFF,
            )
            return

        await super().async_turn_on(**kwargs)

    async def _loop_action(self, *args) -> None:
        """Calculate max safe charge power based on grid phase currents."""
        coordinator = self._data.coordinator
        if coordinator is None or coordinator.data is None:
            _LOGGER.warning("EMS: No coordinator data — stopping charge as safety measure")
            await self._data.handler.write_float(REG_POWER_LIMIT_W, 0.0)
            return

        data = coordinator.data
        phase1 = data.get(REG_CURRENT_PHASE1)
        phase2 = data.get(REG_CURRENT_PHASE2)
        phase3 = data.get(REG_CURRENT_PHASE3)

        if phase1 is None or phase2 is None or phase3 is None:
            _LOGGER.warning("EMS: Phase current read failed — stopping charge as safety measure")
            await self._data.handler.write_float(REG_POWER_LIMIT_W, 0.0)
            return

        fuse_size = self._data.fuse_size
        safe_limit_amps = fuse_size * EMS_SAFETY_MARGIN

        # Available headroom per phase in watts (abs() handles bidirectional current)
        headroom_watts = [
            (safe_limit_amps - abs(phase1)) * EMS_PHASE_VOLTAGE,
            (safe_limit_amps - abs(phase2)) * EMS_PHASE_VOLTAGE,
            (safe_limit_amps - abs(phase3)) * EMS_PHASE_VOLTAGE,
        ]

        # Most constrained phase limits charge power
        max_charge_watts = min(headroom_watts)

        # Clamp: 0 minimum (never discharge), user charge rate as maximum
        target_watts = max(0.0, min(max_charge_watts, self._data.charge_rate))

        _LOGGER.debug(
            "EMS: phase=%.1f/%.1f/%.1f A, fuse=%sA, headroom=%.0f/%.0f/%.0f W → charge=%.0f W",
            phase1, phase2, phase3, fuse_size,
            headroom_watts[0], headroom_watts[1], headroom_watts[2],
            target_watts,
        )

        await self._data.handler.write_float(REG_POWER_LIMIT_W, -target_watts)

    async def _stop_action(self) -> None:
        await self._data.handler.write_float(REG_POWER_LIMIT_W, 0.0)
