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
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

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
    REG_BATTERY_SOC,
    SWITCH_BLOCK_CHARGE,
    SWITCH_CHARGE_START,
    SWITCH_BLOCK_DISCHARGE,
    SWITCH_DISCHARGE_START,
    SWITCH_EMS,
    SWITCH_PREDBAT_CONTROL,
    EMS_SAFETY_MARGIN,
    EMS_PHASE_VOLTAGE,
    SIGNAL_EMS_STATUS_UPDATED,
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
    
    predbat_switch = KostalPredbatControlSwitch(data, entry.entry_id)
    charge_start_switch = KostalChargeStartSwitch(data, entry.entry_id, predbat_switch)

    entities = [
        charge_start_switch,
        KostalDischargeStartSwitch(data, entry.entry_id),
        KostalBlockDischargeSwitch(data, entry.entry_id),
        KostalBlockChargeSwitch(data, entry.entry_id),
        KostalEMSSwitch(data, entry.entry_id, charge_start_switch),
        predbat_switch,
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

    def __init__(self, data, entry_id, predbat_switch=None):
        super().__init__(data, entry_id)
        self._predbat_switch = predbat_switch
        self._predbat_was_charging: bool | None = None
        self._predbat_transition_time: float | None = None
        self._predbat_discharge_blocked: bool = False

    async def _loop_action(self, *args):
        if self._predbat_switch is not None and self._predbat_switch.is_on:
            await self._predbat_loop_action()
        else:
            # Predbat Control just turned off — restore discharge if it was blocked
            if self._predbat_discharge_blocked:
                self._predbat_discharge_blocked = False
                self._predbat_was_charging = None
                self._predbat_transition_time = None
                await self._data.handler.write_float(REG_DISCHARGE_RATE, self._data.discharge_rate)
            # Apply EMS ceiling if active
            target_watts = self._data.charge_rate
            if self._data.ems_status != "inactive":
                target_watts = min(target_watts, self._data.ems_charge_limit_watts)
            await self._data.handler.write_float(REG_POWER_LIMIT_W, -abs(target_watts))

    async def _predbat_loop_action(self) -> None:
        """Predbat-aware loop: charge when predbat_charging is ON, hold SOC floor when OFF."""
        state = self.hass.states.get("binary_sensor.predbat_charging")
        is_charging = state is not None and state.state == "on"

        if is_charging:
            if self._predbat_was_charging is not True:
                _LOGGER.info("Predbat Control: predbat_charging ON — charging")
                self._predbat_transition_time = None
                self._predbat_was_charging = True
            charge_watts = abs(self._data.charge_rate)
            if self._data.ems_status != "inactive":
                charge_watts = min(charge_watts, self._data.ems_charge_limit_watts)
            await self._data.handler.write_float(REG_POWER_LIMIT_W, -charge_watts)
            return

        # Not charging
        if self._predbat_was_charging is True:
            # Transition: charging just stopped — write 0 and start 45s wait
            _LOGGER.info("Predbat Control: predbat_charging OFF — waiting 45s before SOC check")
            await self._data.handler.write_float(REG_POWER_LIMIT_W, 0.0)
            self._predbat_transition_time = time.time()
            self._predbat_was_charging = False
            return

        if self._predbat_was_charging is None:
            # First tick and already not charging — no transition delay needed
            self._predbat_was_charging = False
            self._predbat_transition_time = 0.0

        # Check 45s wait after charge stopped
        elapsed = time.time() - (self._predbat_transition_time or 0.0)
        if elapsed < 45:
            _LOGGER.debug("Predbat Control: %.0fs remaining before SOC check", 45 - elapsed)
            return

        # SOC check against predbat.best_charge_limit
        soc = None
        coordinator = self._data.coordinator
        if coordinator is not None and coordinator.data is not None:
            soc = coordinator.data.get(REG_BATTERY_SOC)

        best_limit_state = self.hass.states.get("predbat.best_charge_limit")
        best_limit = None
        if best_limit_state is not None:
            try:
                best_limit = float(best_limit_state.state)
            except (ValueError, TypeError):
                pass

        if soc is None or best_limit is None:
            _LOGGER.warning(
                "Predbat Control: SOC=%s best_limit=%s unavailable — skipping",
                soc, best_limit,
            )
            return

        floor = best_limit + 1.0
        if soc <= floor:
            # At/below floor — block discharge
            if not self._predbat_discharge_blocked:
                _LOGGER.info(
                    "Predbat Control: SOC=%.1f%% \u2264 floor=%.1f%% — blocking discharge",
                    soc, floor,
                )
                self._predbat_discharge_blocked = True
            await self._data.handler.write_float(REG_DISCHARGE_RATE, 0.0)
        else:
            # Above floor — allow discharge
            if self._predbat_discharge_blocked:
                _LOGGER.info(
                    "Predbat Control: SOC=%.1f%% > floor=%.1f%% — restoring discharge rate",
                    soc, floor,
                )
                self._predbat_discharge_blocked = False
                await self._data.handler.write_float(REG_DISCHARGE_RATE, self._data.discharge_rate)

    async def _stop_action(self):
        await self._data.handler.write_float(REG_POWER_LIMIT_W, 0.0)
        if self._predbat_discharge_blocked:
            self._predbat_discharge_blocked = False
            await self._data.handler.write_float(REG_DISCHARGE_RATE, self._data.discharge_rate)
        self._predbat_was_charging = None
        self._predbat_transition_time = None

class KostalDischargeStartSwitch(KostalBaseSwitch):
    _key = SWITCH_DISCHARGE_START
    _name = "Discharge Start"

    async def _loop_action(self, *args):
        await self._data.handler.write_float(REG_POWER_LIMIT_W, abs(self._data.discharge_rate))

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
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, data, entry_id, charge_start_switch):
        super().__init__(data, entry_id)
        self._charge_start_switch = charge_start_switch
        self._ems_smoothed_limit: float | None = None  # EMA state

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
        """Calculate max safe charge power — only when Charge Start is active."""
        if not self._charge_start_switch.is_on:
            return

        coordinator = self._data.coordinator
        if coordinator is None or coordinator.data is None:
            _LOGGER.warning("EMS: No coordinator data — skipping cycle")
            return

        data = coordinator.data
        phase1 = data.get(REG_CURRENT_PHASE1)
        phase2 = data.get(REG_CURRENT_PHASE2)
        phase3 = data.get(REG_CURRENT_PHASE3)

        if phase1 is None or phase2 is None or phase3 is None:
            _LOGGER.warning("EMS: Phase current read failed — skipping cycle")
            return

        fuse_size = self._data.fuse_size
        safe_limit_amps = fuse_size * EMS_SAFETY_MARGIN

        # Available headroom per phase in watts.
        # Kostal charges equally across all 3 phases, so headroom = amps_left × 3 × voltage.
        headroom_watts = [
            (safe_limit_amps - abs(phase1)) * 3 * EMS_PHASE_VOLTAGE,
            (safe_limit_amps - abs(phase2)) * 3 * EMS_PHASE_VOLTAGE,
            (safe_limit_amps - abs(phase3)) * 3 * EMS_PHASE_VOLTAGE,
        ]

        # Most constrained phase limits charge power
        max_charge_watts = min(headroom_watts)

        # Clamp: 0 minimum (never discharge), use charge_rate as ceiling
        raw_watts = max(0.0, min(max_charge_watts, self._data.charge_rate))

        # Exponential moving average (α=0.3) to prevent oscillation.
        # First cycle: seed with the raw value so we react immediately.
        EMA_ALPHA = 0.3
        if self._ems_smoothed_limit is None:
            self._ems_smoothed_limit = raw_watts
        else:
            self._ems_smoothed_limit = EMA_ALPHA * raw_watts + (1 - EMA_ALPHA) * self._ems_smoothed_limit

        target_watts = round(self._ems_smoothed_limit, 0)

        if target_watts == 0.0:
            new_status = "Blocked"
        elif target_watts < self._data.charge_rate:
            new_status = "Protecting"
        else:
            new_status = "Ok"

        _LOGGER.debug(
            "EMS: phase=%.1f/%.1f/%.1f A, fuse=%sA, headroom=%.0f/%.0f/%.0f W → raw=%.0f W smooth=%.0f W (%s)",
            phase1, phase2, phase3, fuse_size,
            headroom_watts[0], headroom_watts[1], headroom_watts[2],
            raw_watts, target_watts, new_status,
        )

        self._data.ems_charge_limit_watts = target_watts
        self._data.ems_status = new_status
        async_dispatcher_send(
            self.hass, f"{SIGNAL_EMS_STATUS_UPDATED}_{self._entry_id}", new_status
        )
        # EMS does NOT write to Modbus — Charge Start is the sole writer to 1034

    async def _stop_action(self) -> None:
        self._ems_smoothed_limit = None  # Reset EMA when EMS is turned off
        self._data.ems_charge_limit_watts = 15000.0
        self._data.ems_status = "Inactive"
        async_dispatcher_send(
            self.hass, f"{SIGNAL_EMS_STATUS_UPDATED}_{self._entry_id}", "Inactive"
        )
        # EMS does NOT write to Modbus — nothing is written unless a charge switch is active


class KostalPredbatControlSwitch(KostalBaseSwitch, RestoreEntity):
    """Flag-only switch — enables Predbat-aware mode in KostalChargeStartSwitch."""

    _key = SWITCH_PREDBAT_CONTROL
    _name = "Predbat Control"
    _attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        """Restore on/off state after HA restart."""
        last = await self.async_get_last_state()
        if last is not None:
            self._attr_is_on = last.state == "on"
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()
