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
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    GRID_CONTROL_LOOP_INTERVAL,
    GRID_CONTROL_MIN_UPDATE_SECONDS,
    LOOP_INTERVAL,
    PREDBAT_CHARGE_START_DELTA,
    PREDBAT_HOLD_DELTA,
    REG_BATTERY_MAX_CHARGE_POWER_W,
    REG_BATTERY_MAX_DISCHARGE_POWER_W,
    REG_TOTAL_ACTIVE_POWER,
    REG_BATTERY_POWER,
    REG_BATTERY_MAX_CHARGE_LIMIT,
    REG_BATTERY_MAX_DISCHARGE_LIMIT,
    REG_CURRENT_PHASE1,
    REG_CURRENT_PHASE2,
    REG_CURRENT_PHASE3,
    REG_SENSOR_TYPE,
    REG_BATTERY_SOC,
    REG_BATTERY_VOLTAGE,
    REG_IO_OUTPUT_1,
    REG_IO_OUTPUT_2,
    REG_IO_OUTPUT_3,
    REG_IO_OUTPUT_4,
    SWITCH_BLOCK_CHARGE,
    SWITCH_CHARGE_START,
    SWITCH_BLOCK_DISCHARGE,
    SWITCH_DISCHARGE_START,
    SWITCH_EMS,
    SWITCH_INVERTER_CONTROL,
    SWITCH_IO_OUTPUT_1,
    PREDBAT_MODE_ENTITY,
    PREDBAT_ACTIVE_MODES,
    PREDBAT_LOW_POWER_EXPORT_THRESHOLD_WATTS,
    PREDBAT_LOW_POWER_SUSPEND_DELAY_SECONDS,
    PREDBAT_LOW_POWER_RESUME_TOLERANCE_FRACTION,
    PREDBAT_LOW_POWER_RESUME_TOLERANCE_FRACTION_BI,
    POWER_RATE_STEP_W,
    REG_VOLTAGE_PHASE1,
    REG_VOLTAGE_PHASE2,
    REG_VOLTAGE_PHASE3,
    SWITCH_IO_OUTPUT_2,
    SWITCH_IO_OUTPUT_3,
    SWITCH_IO_OUTPUT_4,
    EMS_SAFETY_MARGIN,
    EMS_PHASE_VOLTAGE,
    SIGNAL_EMS_STATUS_UPDATED,
    SIGNAL_INVERTER_CONTROL_UPDATED,
    SIGNAL_PREDBAT_STATUS_UPDATED,
)
from .modbus_handler import KostalModbusHandler

_LOGGER = logging.getLogger(__name__)


def _write_activity_entry(
    hass: HomeAssistant,
    entity_id: str | None,
    name: str,
    message: str,
) -> None:
    """Write a concise entry to Home Assistant's activity log."""
    if not entity_id:
        return

    hass.bus.async_fire(
        "logbook_entry",
        {
            "name": name,
            "message": message,
            "domain": DOMAIN,
            "entity_id": entity_id,
        },
    )

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Kostal Modbus switches."""
    data = hass.data[DOMAIN][entry.entry_id]
    
    charge_start_switch = KostalChargeStartSwitch(data, entry.entry_id)
    discharge_start_switch = KostalDischargeStartSwitch(data, entry.entry_id)
    block_discharge_switch = KostalBlockDischargeSwitch(data, entry.entry_id)
    block_charge_switch = KostalBlockChargeSwitch(data, entry.entry_id)
    exclusive_switches = [
        charge_start_switch,
        discharge_start_switch,
        block_discharge_switch,
        block_charge_switch,
    ]
    inverter_control_switch = None
    if data.source_grid_power_entity:
        inverter_control_switch = KostalInverterControlSwitch(data, entry.entry_id)
        exclusive_switches.append(inverter_control_switch)
    for switch in exclusive_switches:
        switch.set_related_switches(exclusive_switches)

    entities = [
        charge_start_switch,
        discharge_start_switch,
        block_discharge_switch,
        block_charge_switch,
        KostalEMSSwitch(data, entry.entry_id, charge_start_switch),
        # I/O Board outputs (hidden by default)
        KostalIOOutputSwitch(data, entry.entry_id, SWITCH_IO_OUTPUT_1, "I/O Output 1", REG_IO_OUTPUT_1),
        KostalIOOutputSwitch(data, entry.entry_id, SWITCH_IO_OUTPUT_2, "I/O Output 2", REG_IO_OUTPUT_2),
        KostalIOOutputSwitch(data, entry.entry_id, SWITCH_IO_OUTPUT_3, "I/O Output 3", REG_IO_OUTPUT_3),
        KostalIOOutputSwitch(data, entry.entry_id, SWITCH_IO_OUTPUT_4, "I/O Output 4", REG_IO_OUTPUT_4),
    ]
    if inverter_control_switch is not None:
        entities.append(inverter_control_switch)
    async_add_entities(entities)

class KostalBaseSwitch(SwitchEntity):
    """Base class for Kostal switches."""

    _key: str
    _name: str
    _attr_has_entity_name = True
    _attr_should_poll = False
    _auto_resume_on_recovery = False
    _keep_enabled_on_fault = False

    def __init__(self, data, entry_id):
        self._data = data
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_name = self._name
        self._remove_timer = None
        self._start_task = None
        self._attr_is_on = False
        self._related_switches = []
        self._faulted = False
        self._resume_pending = False
        
        # Calculate derived timings
        # Loop interval = Inverter Timeout / 2 (send twice per timeout period)
        self._loop_interval = max(int(self._data.inverter_timeout / 2), 5)
        # Wait time = Inverter Timeout + X (e.g., 15s safety buffer)
        self._wait_time_before_start = self._data.inverter_timeout + 15.0
        self._action_timeout = max(self._wait_time_before_start, 30.0)

        self._data.register_runtime_switch(self)

    def set_related_switches(self, switches):
        self._related_switches = switches

    async def async_will_remove_from_hass(self) -> None:
        # Stop the write loop on unload/reload — otherwise the removed entity
        # keeps writing through the handler, which reconnects by itself
        self._cancel_start_task()
        self._cancel_loop_timer()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "faulted": self._faulted,
            "resume_pending": self._resume_pending,
            "loop_running": self._remove_timer is not None,
            "auto_resume_enabled": self._should_auto_resume_on_recovery(),
        }

    def _should_auto_resume_on_recovery(self) -> bool:
        return self._auto_resume_on_recovery

    def _cancel_loop_timer(self) -> None:
        if self._remove_timer:
            self._remove_timer()
            self._remove_timer = None

    def _cancel_start_task(self) -> None:
        if self._start_task is not None and not self._start_task.done():
            self._start_task.cancel()

    def _set_resume_pending(self, pending: bool) -> None:
        self._resume_pending = pending
        self._data.set_resume_pending(self._key, pending)

    def _write_activity(self, message: str) -> None:
        _write_activity_entry(
            self.hass,
            getattr(self, "entity_id", None),
            str(self.name),
            message,
        )

    def _mark_loop_running(self) -> None:
        self._faulted = False
        if self._resume_pending:
            _LOGGER.info("%s automatic resume completed", self.name)
            self._write_activity("automatic resume completed")
            self._set_resume_pending(False)
        self.async_write_ha_state()

    def _start_periodic_loop(self) -> None:
        self._cancel_loop_timer()
        self._remove_timer = async_track_time_interval(
            self.hass, self._async_handle_loop_tick, timedelta(seconds=self._loop_interval)
        )
        self._mark_loop_running()

    def _schedule_start_loop(self, reason: str) -> None:
        if self._start_task is not None and not self._start_task.done():
            return
        self._start_task = self.hass.async_create_task(self._run_start_loop(reason))

    def handle_connection_restored(self) -> None:
        if self._keep_enabled_on_fault:
            if self._attr_is_on and self._faulted:
                _LOGGER.info("%s cleared communication fault after recovery", self.name)
                self._faulted = False
                self.async_write_ha_state()
            return

        if not self._should_auto_resume_on_recovery() or not self._resume_pending or not self._attr_is_on:
            return

        if self._remove_timer is not None:
            return

        if self._start_task is not None and not self._start_task.done():
            return

        _LOGGER.info("%s scheduling automatic resume after communication recovery", self.name)
        self._write_activity("automatic resume scheduled after communication recovery")
        self._schedule_start_loop("resume")
        self.async_write_ha_state()

    async def _run_start_loop(self, reason: str) -> None:
        try:
            await self._start_loop()
        except asyncio.CancelledError:
            raise
        except Exception as err:
            await self._handle_runtime_fault(err, reason)
        finally:
            self._start_task = None

    async def _run_guarded_action(self, action, phase: str, *args) -> bool:
        try:
            await asyncio.wait_for(action(*args), timeout=self._action_timeout)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as err:
            await self._handle_runtime_fault(err, phase)
            return False

    async def _handle_runtime_fault(self, err: Exception, phase: str) -> None:
        if not self._attr_is_on:
            return

        self._cancel_loop_timer()
        self._data.mark_communication_lost(f"{self.name}: {err}")
        self._faulted = True
        await self._data.handler.close()
        self._on_communication_fault()

        if self._should_auto_resume_on_recovery():
            self._data.last_stop_time = time.time()
            self._set_resume_pending(True)
            _LOGGER.warning(
                "%s paused after %s failure and will retry after recovery: %s",
                self.name,
                phase,
                err,
            )
            self._write_activity(f"paused after {phase} failure")
        elif self._keep_enabled_on_fault:
            _LOGGER.warning(
                "%s remains enabled after %s failure: %s",
                self.name,
                phase,
                err,
            )
            self._write_activity(f"communication issue during {phase}")
        else:
            self._data.last_stop_time = time.time()
            self._set_resume_pending(False)
            self._attr_is_on = False
            _LOGGER.warning(
                "%s turned off after %s failure: %s",
                self.name,
                phase,
                err,
            )
            self._write_activity(f"turned off after {phase} failure")

        self.async_write_ha_state()

    def _on_communication_fault(self) -> None:
        """Hook for subclasses that need to clear transient runtime state."""

    async def _async_handle_loop_tick(self, *args) -> None:
        if not self._attr_is_on:
            return
        await self._run_guarded_action(self._loop_action, "periodic loop", *args)

    async def _run_stop_action(self) -> None:
        try:
            await asyncio.wait_for(self._stop_action(), timeout=self._action_timeout)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            self._data.mark_communication_lost(f"{self.name}: {err}")
            _LOGGER.warning("%s stop action failed: %s", self.name, err)
            await self._data.handler.close()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if self._attr_is_on:
            _LOGGER.debug("%s turn_on ignored because switch is already on", self.name)
            self.async_write_ha_state()
            return

        # Ensure mutually exclusive behavior
        for switch in self._related_switches:
            if switch is not self and switch.is_on:
                await switch.async_turn_off()

        self._faulted = False
        self._set_resume_pending(False)
        self._attr_is_on = True
        self.async_write_ha_state()
        self._schedule_start_loop("manual start")

    async def _start_loop(self) -> None:
        """Background task: wait if needed, then start the periodic loop."""
        time_since_last_stop = time.time() - self._data.last_stop_time
        if time_since_last_stop < self._wait_time_before_start:
            sleep_duration = self._wait_time_before_start - time_since_last_stop
            _LOGGER.info(f"Waiting {sleep_duration:.1f}s before starting {self.name} (mandatory delay)")
            await asyncio.sleep(sleep_duration)
            if not self._attr_is_on:
                return

        # Kør pre-start (f.eks. nulstil 1038/1040) først efter eventuel ventetid,
        # så ingen Modbus-besked nulstiller inverterens timeout på effekt-setpunktet under ventetiden.
        if not await self._run_guarded_action(self._pre_start_action, "pre-start"):
            return
        if not self._attr_is_on:
            return
        if not await self._run_guarded_action(self._loop_action, "initial loop"):
            return
        if self._attr_is_on:
            self._start_periodic_loop()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if not self._attr_is_on:
            self.async_write_ha_state()
            return

        self._cancel_start_task()
        self._cancel_loop_timer()
        self._faulted = False
        self._set_resume_pending(False)
        self._attr_is_on = False
        await self._run_stop_action()
        self.async_write_ha_state()

    def _max_discharge_watts(self) -> float:
        """Read battery's own max discharge limit from register 1078."""
        coordinator = self._data.coordinator
        if coordinator is not None and coordinator.data is not None:
            return coordinator.data.get(REG_BATTERY_MAX_DISCHARGE_LIMIT) or 0.0
        return 0.0

    def _max_charge_watts(self) -> float:
        """Read battery's own max charge limit from register 1076."""
        coordinator = self._data.coordinator
        if coordinator is not None and coordinator.data is not None:
            return coordinator.data.get(REG_BATTERY_MAX_CHARGE_LIMIT) or 0.0
        return 0.0

    def _current_discharge_limit_watts(self) -> float:
        """Read the currently applied discharge limit from register 1040."""
        coordinator = self._data.coordinator
        if coordinator is not None and coordinator.data is not None:
            return coordinator.data.get(REG_BATTERY_MAX_DISCHARGE_POWER_W) or 0.0
        return 0.0

    async def _restore_max_discharge_limit(self) -> bool:
        """Restore register 1040 to the battery's current maximum discharge limit."""
        max_discharge_watts = self._max_discharge_watts()
        if max_discharge_watts <= 0.0:
            _LOGGER.warning(
                "Predbat Control: cannot restore discharge limit because max discharge is unavailable"
            )
            return False

        await self._data.handler.write_float(REG_BATTERY_MAX_DISCHARGE_POWER_W, max_discharge_watts)
        return True

    async def _write_power_setpoint(self, watts: float) -> None:
        """Write a signed battery power setpoint in Watts (negative = charge).

        Clamped to the maximum battery control power, then written to the
        absolute setpoint register — 1034 (DC) on hybrid inverters, 1026 (AC)
        on the BI.
        """
        setpoint = round(self._data.clamp_power_setpoint_w(watts))
        _LOGGER.debug("%s: power setpoint %s W to register %d", self.name, setpoint, self._data.charge_discharge_reg)
        await self._data.handler.write_float(self._data.charge_discharge_reg, float(setpoint))

    def _stop_setpoint_watts_from_active_power(self) -> float:
        """Estimate a signed stop setpoint from grid-point power and battery power.

        For a smart meter at the grid connection point, register 252 is:
        - positive when importing from grid
        - negative when exporting to grid

        Battery power is:
        - negative while charging
        - positive while discharging

        Adding the two removes the battery contribution and gives an estimate of
        the underlying house demand seen at the grid point.

        Result, in Watts and clamped to the maximum battery control power:
        - positive setpoint when the house still needs battery discharge
        - negative setpoint when PV surplus is available for battery charge
        """
        coordinator = self._data.coordinator
        if coordinator is None or coordinator.data is None:
            _LOGGER.debug("Stop setpoint: no coordinator data available")
            return 0.0

        total_active_power = coordinator.data.get(REG_TOTAL_ACTIVE_POWER)
        battery_power = coordinator.data.get(REG_BATTERY_POWER)

        if total_active_power is None or battery_power is None:
            _LOGGER.debug(
                "Stop setpoint: insufficient data total_active_power=%s battery_power=%s",
                total_active_power,
                battery_power,
            )
            return 0.0

        # Gridpoint meter: import is positive, feed-in is negative.
        # Battery power is negative while charging and positive while discharging.
        # Summing them estimates the net load after PV contribution, which is
        # the signed stop setpoint.
        net_load_after_pv_watts = total_active_power + battery_power
        stop_setpoint_watts = round(self._data.clamp_power_setpoint_w(net_load_after_pv_watts))

        _LOGGER.debug(
            "Stop setpoint: total_active_power=%.1fW battery_power=%.1fW net_load_after_pv=%.1fW max_power=%s stop_setpoint=%sW",
            total_active_power,
            battery_power,
            net_load_after_pv_watts,
            self._data.max_battery_power_w(),
            stop_setpoint_watts,
        )

        return float(stop_setpoint_watts)

    async def _pre_start_action(self):
        """Køres straks ved start, inden eventuel ventetid på effekt-setpunktet."""
        pass

    async def _loop_action(self, *args):
        """Action performed periodically."""
        pass

    async def _stop_action(self):
        """Action performed when stopping."""
        pass

class KostalChargeStartSwitch(KostalBaseSwitch):
    _key = SWITCH_CHARGE_START
    _name = "Charge Start"
    _auto_resume_on_recovery = True

    def __init__(self, data, entry_id):
        super().__init__(data, entry_id)
        self._predbat_was_charging: bool | None = None
        self._predbat_transition_time: float | None = None
        self._predbat_startup_block_until: float | None = None
        self._predbat_discharge_blocked: bool = False
        self._predbat_low_power_capping: bool = False
        self._predbat_low_power_suspended: bool = False
        self._predbat_low_power_export_since: float | None = None

    def _is_predbat_active(self) -> bool:
        """Return True when select.predbat_mode exists and is in an active control mode."""
        state = self.hass.states.get(PREDBAT_MODE_ENTITY)
        if state is None:
            return False
        return state.state in PREDBAT_ACTIVE_MODES

    def _set_predbat_status(self, status: str) -> None:
        if self._data.predbat_status == status:
            return

        self._data.predbat_status = status
        async_dispatcher_send(
            self.hass, f"{SIGNAL_PREDBAT_STATUS_UPDATED}_{self._entry_id}", status
        )

    def _predbat_car_hold_active(self) -> bool:
        """Return True when Predbat has entered 'Hold for car' without an active charge window.

        Predbat sets its status to "Hold for car" when battery discharge should
        be blocked while the car charges, but there is no grid-charge window
        active.  When a charge window IS active Predbat appends ", Hold for car"
        to a status that starts with "Charging", so checking for the absence of
        "Charging" (capital-C) distinguishes the two cases.
        """
        state = self.hass.states.get("predbat.status")
        if state is None:
            return False
        status = state.state
        return "Hold for car" in status and "Charging" not in status

    def _is_predbat_low_power_active(self) -> bool:
        """Return True when switch.predbat_set_charge_low_power is turned on."""
        state = self.hass.states.get("switch.predbat_set_charge_low_power")
        if state is None:
            return False
        return state.state == "on"

    def _predbat_low_power_rate_watts(self) -> float | None:
        """Return input_number.predbat_charge_rate parsed as Watts, or None."""
        rate_state = self.hass.states.get("input_number.predbat_charge_rate")
        if rate_state is None:
            _LOGGER.warning("Predbat low power: input_number.predbat_charge_rate not found")
            return None
        try:
            return float(rate_state.state)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Predbat low power: input_number.predbat_charge_rate has non-numeric state '%s'",
                rate_state.state,
            )
            return None

    def _predbat_low_power_charge_watts(self) -> float | None:
        """Return the Predbat low power charge rate in Watts.

        Reads input_number.predbat_charge_rate. Returns None when low power
        mode is inactive or when the entity is unavailable.
        """
        if not self._is_predbat_low_power_active():
            return None

        rate_watts = self._predbat_low_power_rate_watts()
        if rate_watts is None:
            return None
        return max(0.0, rate_watts)

    def _predbat_low_power_resume_tolerance(self) -> float:
        if self._data.is_battery_inverter:
            return PREDBAT_LOW_POWER_RESUME_TOLERANCE_FRACTION_BI
        return PREDBAT_LOW_POWER_RESUME_TOLERANCE_FRACTION

    def _predbat_low_power_export_suspend_check(self) -> bool:
        """Suspend/resume the low-power charge setpoint writes based on grid export.

        While the low-power charge rate is capping the charge target, sustained
        grid export means the inverter's own internal control (once the
        power setpoint write stops refreshing) will drive the grid point to 0
        faster than this integration's own loop can. When export has stayed
        at or below -PREDBAT_LOW_POWER_EXPORT_THRESHOLD_WATTS for
        PREDBAT_LOW_POWER_SUSPEND_DELAY_SECONDS, stop writing. Once suspended,
        resume immediately (no delay, but with a tolerance — see
        PREDBAT_LOW_POWER_RESUME_TOLERANCE_FRACTION) as soon as battery
        charging power drops meaningfully below the low-power setpoint, e.g.
        because PV production fades.

        Returns True when this tick's write should be skipped (still
        suspended), False when the write should proceed as normal.
        """
        coordinator = self._data.coordinator
        grid_power = None
        battery_power = None
        if coordinator is not None and coordinator.data is not None:
            grid_power = coordinator.data.get(REG_TOTAL_ACTIVE_POWER)
            battery_power = coordinator.data.get(REG_BATTERY_POWER)

        if self._predbat_low_power_suspended:
            if battery_power is None:
                # No fresh reading this tick — stay suspended rather than
                # treating missing data as a reason to resume.
                return True

            rate_watts = self._predbat_low_power_rate_watts() or 0.0
            charging_watts = -battery_power if battery_power < 0 else 0.0
            tolerance = self._predbat_low_power_resume_tolerance()
            resume_threshold_watts = rate_watts * (1 - tolerance)
            if charging_watts >= resume_threshold_watts:
                # Inverter is still meeting the low-power target (within
                # tolerance) from PV alone.
                return True

            _LOGGER.info(
                "Predbat low power: charging power %.0fW below setpoint %.0fW (tolerance %.0f%%) — resuming charge setpoint writes",
                charging_watts,
                rate_watts,
                tolerance * 100,
            )
            self._write_activity("Predbat low power: resuming charge setpoint (charging below target)")
            self._predbat_low_power_suspended = False
            self._predbat_low_power_export_since = None
            return False

        if grid_power is not None and grid_power <= -PREDBAT_LOW_POWER_EXPORT_THRESHOLD_WATTS:
            if self._predbat_low_power_export_since is None:
                self._predbat_low_power_export_since = time.time()
            elif time.time() - self._predbat_low_power_export_since >= PREDBAT_LOW_POWER_SUSPEND_DELAY_SECONDS:
                _LOGGER.info(
                    "Predbat low power: grid export >= %.0fW for %.0fs — suspending charge setpoint writes",
                    PREDBAT_LOW_POWER_EXPORT_THRESHOLD_WATTS,
                    PREDBAT_LOW_POWER_SUSPEND_DELAY_SECONDS,
                )
                self._write_activity(
                    "Predbat low power: pausing charge setpoint — inverter self-regulating to 0 export"
                )
                self._predbat_low_power_suspended = True
                self._predbat_low_power_export_since = None
                return True
        else:
            self._predbat_low_power_export_since = None

        return False

    def _predbat_limit_decision(
        self,
    ) -> tuple[float | None, float | None, float | None, bool | None]:
        coordinator = self._data.coordinator
        soc = None
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
            return soc, None, None, None

        charge_start_limit = max(0.0, best_limit - PREDBAT_CHARGE_START_DELTA)
        hold_limit = min(100.0, best_limit + PREDBAT_HOLD_DELTA)
        if best_limit >= 100.0 and self._predbat_was_charging is True:
            return soc, charge_start_limit, hold_limit, True
        if self._predbat_was_charging is True:
            should_charge_now = soc < hold_limit
        else:
            should_charge_now = soc <= charge_start_limit
        return soc, charge_start_limit, hold_limit, should_charge_now

    def _predbat_charge_stop_watts(self) -> float:
        soc, charge_start_limit, hold_limit, should_charge_now = self._predbat_limit_decision()
        if should_charge_now is None:
            _LOGGER.warning(
                "Predbat Control: SOC=%s start_limit=%s hold_limit=%s unavailable during charge stop — using signed stop setpoint",
                soc,
                charge_start_limit,
                hold_limit,
            )
            return self._stop_setpoint_watts_from_active_power()

        if not should_charge_now:
            _LOGGER.info(
                "Predbat Control: SOC=%.1f%% >= charge_start_limit=%.1f%% and not below hold_limit=%.1f%% charge threshold — writing neutral stop setpoint for hold",
                soc,
                charge_start_limit,
                hold_limit,
            )
            self._write_activity(
                f"Predbat hold: neutral stop setpoint because SOC={soc:.1f}% is above start limit {charge_start_limit:.1f}%"
            )
            return 0.0

        stop_setpoint_watts = self._stop_setpoint_watts_from_active_power()
        _LOGGER.info(
            "Predbat Control: SOC=%.1f%% below active threshold (start_limit=%.1f%% hold_limit=%.1f%%) — using signed stop setpoint %sW",
            soc,
            charge_start_limit,
            hold_limit,
            stop_setpoint_watts,
        )
        return stop_setpoint_watts

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self._is_predbat_active():
            # self._predbat_startup_block_until = time.time() + 15.0
            self._predbat_startup_block_until = None
            _soc, _charge_start_limit, _hold_limit, should_charge_now = self._predbat_limit_decision()
            if should_charge_now is None:
                self._set_predbat_status("Waiting")
            elif should_charge_now:
                self._set_predbat_status("Charge")
            elif self._predbat_car_hold_active():
                self._set_predbat_status("Hold for car")
            else:
                self._set_predbat_status("Hold")
        else:
            self._predbat_startup_block_until = None
            self._set_predbat_status("Inactive")
        await super().async_turn_on(**kwargs)

    def _predbat_startup_write_blocked(self) -> bool:
        if self._predbat_startup_block_until is None:
            return False
        remaining = self._predbat_startup_block_until - time.time()
        if remaining > 0:
            _LOGGER.debug("Predbat Control: write to %s blocked for %.0fs more", self._data.charge_discharge_reg, remaining)
            return True
        self._predbat_startup_block_until = None
        return False

    async def _start_loop(self) -> None:
        """Custom startup for Charge Start in Predbat mode.

        With Predbat enabled, evaluate the first charge or hold decision
        immediately. Reads may continue and writes to the power setpoint are no
        longer delayed during startup.
        """
        if self._is_predbat_active():
            # Respect the same last_stop_time settling delay as the base class.
            # A previous switch (e.g. Discharge Start) may have written the power setpoint recently.
            time_since_last_stop = time.time() - self._data.last_stop_time
            if time_since_last_stop < self._wait_time_before_start:
                sleep_duration = self._wait_time_before_start - time_since_last_stop
                _LOGGER.info(
                    "Predbat Control: waiting %.1fs before first write (inverter settling after previous stop)",
                    sleep_duration,
                )
                await asyncio.sleep(sleep_duration)

            if not self._attr_is_on:
                self._set_predbat_status("Inactive")
                return

            soc, charge_start_limit, hold_limit, should_charge_now = self._predbat_limit_decision()

            if should_charge_now is None:
                _LOGGER.warning(
                    "Predbat Control: startup decision unavailable because SOC=%s, start_limit=%s or hold_limit=%s is missing",
                    soc,
                    charge_start_limit,
                    hold_limit,
                )
                # Power setpoint not written — no transition wait needed
                self._predbat_was_charging = False
                self._predbat_transition_time = None
                self._set_predbat_status("Waiting")
            elif should_charge_now:
                _LOGGER.info(
                    "Predbat Control: startup decision = charge because SOC=%.1f%% <= charge_start_limit=%.1f%%",
                    soc,
                    charge_start_limit,
                )
                self._write_activity(
                    f"Predbat startup: charge because SOC={soc:.1f}% <= start limit {charge_start_limit:.1f}%"
                )
                self._predbat_was_charging = True
                self._predbat_transition_time = None
                self._set_predbat_status("Charge")
            else:
                car_hold = self._predbat_car_hold_active()
                _LOGGER.info(
                    "Predbat Control: startup decision = %s because SOC=%.1f%% is above charge_start_limit=%.1f%%",
                    "hold for car" if car_hold else "hold",
                    soc,
                    charge_start_limit,
                )
                self._write_activity(
                    f"Predbat startup: {'hold for car' if car_hold else 'hold'} because SOC={soc:.1f}% is above start limit {charge_start_limit:.1f}%"
                )
                # Power setpoint not written — inverter already in internal control, go directly to hold
                self._predbat_was_charging = False
                self._predbat_transition_time = None
                self._set_predbat_status("Hold for car" if car_hold else "Hold")

            if not await self._run_guarded_action(self._loop_action, "initial predbat loop"):
                return
            if self._attr_is_on:
                self._start_periodic_loop()
            return

        await super()._start_loop()

    async def _loop_action(self, *args):
        if not self._attr_is_on:
            self._set_predbat_status("Inactive")
            return
        if self._is_predbat_active():
            await self._predbat_loop_action()
        else:
            self._set_predbat_status("Inactive")
            # Normal charge — no Predbat Control
            await self._write_power_setpoint(-self._charge_target_watts())

    def _charge_target_watts(self) -> float:
        """Charge rate in Watts, capped by EMS Grid Protection while it is active."""
        target_watts = abs(self._data.charge_power_w())
        if self._data.ems_status != "Inactive" and self._data.ems_charge_limit_w is not None:
            target_watts = min(target_watts, self._data.ems_charge_limit_w)
        return target_watts

    async def _predbat_loop_action(self) -> None:
        """Predbat-aware loop: charge below best_charge_limit, otherwise hold SOC."""
        if not self._attr_is_on:
            _LOGGER.debug("Predbat Control: Charge Start er OFF — ignorerer Predbat-evaluering")
            self._set_predbat_status("Inactive")
            return
        soc, charge_start_limit, hold_limit, should_charge_now = self._predbat_limit_decision()
        if should_charge_now is None:
            _LOGGER.warning(
                "Predbat Control: SOC=%s start_limit=%s hold_limit=%s unavailable — skipping",
                soc,
                charge_start_limit,
                hold_limit,
            )
            self._set_predbat_status("Waiting")
            return
        assert soc is not None and hold_limit is not None

        if self._predbat_car_hold_active():
            _LOGGER.debug(
                "Predbat Control: predbat.status contains 'Hold for car' (no active charge window) — overriding to hold"
            )
            should_charge_now = False

        if should_charge_now:
            if not self._predbat_low_power_suspended:
                self._set_predbat_status("Charge")
            if self._predbat_was_charging is not True:
                _LOGGER.info(
                    "Predbat Control: SOC=%.1f%% <= charge_start_limit=%.1f%% — charging",
                    soc,
                    charge_start_limit,
                )
                self._predbat_transition_time = None
                self._predbat_was_charging = True
            if self._predbat_discharge_blocked or self._current_discharge_limit_watts() <= 0.0:
                if await self._restore_max_discharge_limit():
                    self._predbat_discharge_blocked = False
            charge_watts = self._charge_target_watts()
            low_power_watts = self._predbat_low_power_charge_watts()
            if low_power_watts is not None and low_power_watts < charge_watts:
                if not self._predbat_low_power_capping:
                    _LOGGER.info(
                        "Predbat low power: capping charge rate from %.0fW to %.0fW (input_number.predbat_charge_rate)",
                        charge_watts,
                        low_power_watts,
                    )
                    self._write_activity(
                        f"Predbat low power: charge rate capped to {low_power_watts:.0f} W"
                    )
                    self._predbat_low_power_capping = True
                charge_watts = low_power_watts

                if self._predbat_low_power_export_suspend_check():
                    self._set_predbat_status("Low Power Suspended")
                    return
                self._set_predbat_status("Charge")
            else:
                if self._predbat_low_power_capping:
                    _LOGGER.info("Predbat low power: charge rate cap released")
                    self._write_activity("Predbat low power: charge rate cap released")
                self._predbat_low_power_capping = False
                self._predbat_low_power_suspended = False
                self._predbat_low_power_export_since = None
                self._set_predbat_status("Charge")
            if not self._attr_is_on:
                return
            if self._predbat_startup_write_blocked():
                return
            await self._write_power_setpoint(-charge_watts)
            return

        if self._predbat_was_charging is None:
            # Power setpoint was never written in this session — no transition wait needed
            self._predbat_was_charging = False
            self._predbat_transition_time = None

        self._predbat_low_power_suspended = False
        self._predbat_low_power_export_since = None

        # Not charging
        if self._predbat_was_charging is True:
            # Transition: charging just stopped.
            # Write either 0 or a signed stop setpoint, then keep the normal 45s wait
            # before the hold evaluation and any discharge block on 1040.
            _LOGGER.info(
                "Predbat Control: SOC=%.1f%% >= hold_limit=%.1f%% — waiting 45s before hold evaluation",
                soc,
                hold_limit,
            )
            self._write_activity(
                f"Predbat waiting 45s: SOC={soc:.1f}% >= hold limit {hold_limit:.1f}%"
            )
            self._set_predbat_status("Waiting")
            await self._write_power_setpoint(self._predbat_charge_stop_watts())
            self._predbat_transition_time = time.time()
            self._predbat_was_charging = False
            return

        # Check 45s wait after charge stopped
        elapsed = time.time() - (self._predbat_transition_time or 0.0)
        if elapsed < 45:
            self._set_predbat_status("Waiting")
            # Let the inverter return to internal control before forcing 1040 to 0.
            # Blocking discharge too early here can also block PV charging.
            _LOGGER.debug("Predbat Control: %.0fs remaining before SOC check", 45 - elapsed)
            return

        # Final guard before SOC comparison — Charge Start is master switch
        if not self._attr_is_on:
            return

        car_hold = self._predbat_car_hold_active()
        hold_status = "Hold for car" if car_hold else "Hold"
        self._set_predbat_status(hold_status)
        if car_hold or soc <= hold_limit:
            # At/below hold limit — block discharge
            if not self._predbat_discharge_blocked:
                _LOGGER.info(
                    "Predbat Control: SOC=%.1f%% <= hold_limit=%.1f%% — blocking discharge (%s)",
                    soc, hold_limit, hold_status,
                )
                self._write_activity(
                    f"Predbat {hold_status.lower()}: blocking discharge because SOC={soc:.1f}% <= hold limit {hold_limit:.1f}%"
                )
                self._predbat_discharge_blocked = True
            await self._data.handler.write_float(REG_BATTERY_MAX_DISCHARGE_POWER_W, 0.0)
        else:
            # Above hold limit — restore free discharge if 1040 was previously forced to zero.
            discharge_limit_is_blocked = self._current_discharge_limit_watts() <= 0.0
            if self._predbat_discharge_blocked or discharge_limit_is_blocked:
                _LOGGER.info(
                    "Predbat Control: SOC=%.1f%% > hold_limit=%.1f%% — releasing inverter",
                    soc, hold_limit,
                )
                self._write_activity(
                    f"Predbat hold: releasing inverter because SOC={soc:.1f}% > hold limit {hold_limit:.1f}%"
                )
                if await self._restore_max_discharge_limit():
                    self._predbat_discharge_blocked = False

    async def _stop_action(self):
        # Only write a signed stop setpoint if we were actually charging.
        # In predbat hold mode (_predbat_was_charging is False), that stop
        # setpoint was already written when Predbat switched from charge to hold.
        # In normal mode (predbat switch OFF), we always write it here.
        if not self._is_predbat_active() or self._predbat_was_charging is True:
            # Always use live power balance on manual stop — the 0.0 hold-transition
            # setpoint only makes sense when charge completes naturally in _predbat_loop_action.
            await self._write_power_setpoint(self._stop_setpoint_watts_from_active_power())
        self._data.last_stop_time = time.time()
        self._set_predbat_status("Inactive")
        if self._predbat_discharge_blocked:
            self._predbat_discharge_blocked = False
            await self._restore_max_discharge_limit()
        self._predbat_was_charging = None
        self._predbat_transition_time = None
        self._predbat_startup_block_until = None
        self._predbat_low_power_capping = False
        self._predbat_low_power_suspended = False
        self._predbat_low_power_export_since = None
        # Close the Modbus connection so the inverter sees a clean disconnect.
        # It will reconnect automatically on the next read/write.
        await self._data.handler.close()

    def _on_communication_fault(self) -> None:
        self._set_predbat_status("Inactive")
        self._predbat_low_power_suspended = False
        self._predbat_low_power_export_since = None

class KostalDischargeStartSwitch(KostalBaseSwitch):
    _key = SWITCH_DISCHARGE_START
    _name = "Discharge Start"
    _auto_resume_on_recovery = True

    async def _loop_action(self, *args):
        if not self._attr_is_on:
            return
        await self._write_power_setpoint(abs(self._data.discharge_power_w()))

    async def _stop_action(self):
        self._data.last_stop_time = time.time()
        # Recalculate the signed stop setpoint so the inverter can settle into
        # either discharge, neutral, or charge depending on live net power.
        await self._write_power_setpoint(self._stop_setpoint_watts_from_active_power())
        await self._data.handler.close()


class KostalBlockDischargeSwitch(KostalBaseSwitch):
    _key = SWITCH_BLOCK_DISCHARGE
    _name = "Block Discharge"
    _auto_resume_on_recovery = True

    async def _loop_action(self, *args):
        if not self._attr_is_on:
            return
        # Write discharge rate 0 to Block Discharge (1040)
        # MUST BE POSITIVE (0 is positive)
        await self._data.handler.write_float(REG_BATTERY_MAX_DISCHARGE_POWER_W, 0.0)

    async def _stop_action(self):
        self._data.last_stop_time = time.time()
        await self._data.handler.write_float(REG_BATTERY_MAX_DISCHARGE_POWER_W, self._max_discharge_watts())
        await self._data.handler.close()

class KostalBlockChargeSwitch(KostalBaseSwitch):
    _key = SWITCH_BLOCK_CHARGE
    _name = "Block Charge"
    _auto_resume_on_recovery = True

    async def _loop_action(self, *args):
        if not self._attr_is_on:
            return
        # Write 0 to charge rate (Block Charge) via 1038
        # MUST BE POSITIVE (0 is positive)
        await self._data.handler.write_float(REG_BATTERY_MAX_CHARGE_POWER_W, 0.0)

    async def _stop_action(self):
        self._data.last_stop_time = time.time()
        await self._data.handler.write_float(REG_BATTERY_MAX_CHARGE_POWER_W, self._max_charge_watts())
        await self._data.handler.close()


class KostalEMSSwitch(KostalBaseSwitch, RestoreEntity):
    _key = SWITCH_EMS
    _name = "EMS Grid Protection"
    _attr_entity_category = EntityCategory.CONFIG
    _keep_enabled_on_fault = True

    def __init__(self, data, entry_id, charge_start_switch):
        super().__init__(data, entry_id)
        self._charge_start_switch = charge_start_switch
        self._ems_smoothed_limit: float | None = None  # EMA state

    async def async_added_to_hass(self) -> None:
        """Restore on/off state after HA restart."""
        last = await self.async_get_last_state()
        if last is not None:
            self._attr_is_on = last.state == "on"

        if self._attr_is_on:
            self._schedule_start_loop("state restore")

        self.async_write_ha_state()

    def _set_ems_status(self, status: str) -> None:
        if self._data.ems_status == status:
            return

        previous_status = self._data.ems_status
        self._data.ems_status = status
        async_dispatcher_send(
            self.hass, f"{SIGNAL_EMS_STATUS_UPDATED}_{self._entry_id}", status
        )

        if status == "Blocked":
            self._write_activity("EMS blocked charging")
        elif status == "Protecting":
            self._write_activity("EMS is limiting charge power")
        elif status == "Ok" and previous_status in {"Blocked", "Protecting"}:
            self._write_activity("EMS returned to normal operation")

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
        if not self._attr_is_on:
            return
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
        voltages = [
            self._phase_voltage(data.get(address))
            for address in (REG_VOLTAGE_PHASE1, REG_VOLTAGE_PHASE2, REG_VOLTAGE_PHASE3)
        ]

        # Battery charging is spread evenly over the three phases, so each
        # phase allows its own current headroom times three at its voltage
        headroom_watts = min(
            (safe_limit_amps - max(0.0, phase1)) * 3 * voltages[0],
            (safe_limit_amps - max(0.0, phase2)) * 3 * voltages[1],
            (safe_limit_amps - max(0.0, phase3)) * 3 * voltages[2],
        )

        charge_rate_watts = abs(self._data.charge_power_w())
        prev_limit = self._ems_smoothed_limit if self._ems_smoothed_limit is not None else charge_rate_watts
        raw_watts = max(0.0, min(prev_limit + headroom_watts, charge_rate_watts))

        EMA_ALPHA = 0.3
        if self._ems_smoothed_limit is None:
            self._ems_smoothed_limit = raw_watts
        else:
            self._ems_smoothed_limit = EMA_ALPHA * raw_watts + (1 - EMA_ALPHA) * self._ems_smoothed_limit

        target_watts = float(round(self._ems_smoothed_limit))

        if target_watts <= 0.0:
            new_status = "Blocked"
        elif target_watts < charge_rate_watts - POWER_RATE_STEP_W:
            # A margin keeps small moves of a rate that follows the battery
            # voltage from reading as protection
            new_status = "Protecting"
        else:
            new_status = "Ok"

        _LOGGER.debug(
            "EMS: phase=%.1f/%.1f/%.1f A at %.0f/%.0f/%.0f V, fuse=%sA, headroom=%.0f W, charge_rate=%.0f W → raw=%.0f W smooth=%.0f W (%s)",
            phase1, phase2, phase3, *voltages, fuse_size,
            headroom_watts, charge_rate_watts,
            raw_watts, target_watts, new_status,
        )

        self._data.ems_charge_limit_w = target_watts
        self._set_ems_status(new_status)
        # EMS does NOT write to Modbus — Charge Start is the sole writer to the power setpoint

    @staticmethod
    def _phase_voltage(voltage: float | None) -> float:
        """Measured phase voltage, or the nominal voltage when the meter reports none."""
        if voltage is None or voltage < 100.0:
            return EMS_PHASE_VOLTAGE
        return voltage

    async def _stop_action(self) -> None:
        self._ems_smoothed_limit = None
        self._data.ems_charge_limit_w = None
        self._set_ems_status("Inactive")
        # EMS does NOT write to Modbus — nothing is written unless a charge switch is active

    def _on_communication_fault(self) -> None:
        self._ems_smoothed_limit = None


class KostalInverterControlSwitch(KostalBaseSwitch, RestoreEntity):
    """Trim grid import/export from an external Home Assistant grid-power entity.

    Meant for inverters without a smart meter. The entity must read positive
    while importing from the grid and negative while exporting.
    """

    _key = SWITCH_INVERTER_CONTROL
    _name = "Inverter Control"
    _auto_resume_on_recovery = True

    def __init__(self, data, entry_id):
        super().__init__(data, entry_id)
        # The timer is only the fallback; normally a new grid reading triggers
        # the calculation (see _handle_grid_update)
        self._loop_interval = GRID_CONTROL_LOOP_INTERVAL
        self._unsub_grid_listener = None
        self._cancel_deferred_update = None
        self._last_calculation = 0.0
        self._calculation_lock = asyncio.Lock()

    def _start_periodic_loop(self) -> None:
        super()._start_periodic_loop()
        entity_id = self._data.source_grid_power_entity
        if entity_id:
            self._unsub_grid_listener = async_track_state_change_event(
                self.hass, [entity_id], self._handle_grid_update
            )

    def _cancel_loop_timer(self) -> None:
        super()._cancel_loop_timer()
        if self._unsub_grid_listener is not None:
            self._unsub_grid_listener()
            self._unsub_grid_listener = None
        if self._cancel_deferred_update is not None:
            self._cancel_deferred_update()
            self._cancel_deferred_update = None

    @callback
    def _handle_grid_update(self, event) -> None:
        """Recalculate on every new grid reading, at most once per GRID_CONTROL_MIN_UPDATE_SECONDS."""
        if self._remove_timer is None or self._cancel_deferred_update is not None:
            return
        wait = GRID_CONTROL_MIN_UPDATE_SECONDS - (time.monotonic() - self._last_calculation)
        if wait > 0:
            # Too soon — run once the interval has passed, with the newest reading
            self._cancel_deferred_update = async_call_later(self.hass, wait, self._async_deferred_update)
            return
        self.hass.async_create_task(self._async_grid_update_tick())

    async def _async_deferred_update(self, _now) -> None:
        self._cancel_deferred_update = None
        await self._async_grid_update_tick()

    async def _async_grid_update_tick(self) -> None:
        # The loop may have been stopped between scheduling and running
        if self._remove_timer is None:
            return
        await self._async_handle_loop_tick()

    def _publish_state(
        self,
        status: str,
        *,
        target_watts: float | None = None,
        house_load_w: float | None = None,
    ) -> None:
        self._data.inverter_control_status = status
        self._data.inverter_control_target_w = target_watts
        self._data.inverter_control_house_load_w = house_load_w
        async_dispatcher_send(self.hass, f"{SIGNAL_INVERTER_CONTROL_UPDATED}_{self._entry_id}")

    async def async_added_to_hass(self) -> None:
        """Restore inverter control state after HA restart."""
        last = await self.async_get_last_state()
        if last is not None:
            self._attr_is_on = last.state == "on"

        if self._attr_is_on:
            self._schedule_start_loop("state restore")

        self.async_write_ha_state()

    def _get_float_state(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in {"unknown", "unavailable", "none", "None"}:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _grid_inputs(self, battery_power: int | None) -> dict[str, float] | None:
        coordinator = self._data.coordinator
        if coordinator is None or coordinator.data is None:
            _LOGGER.debug("Inverter Control: no coordinator data available")
            return None

        soc = coordinator.data.get(REG_BATTERY_SOC)
        raw_grid_power = self._get_float_state(self._data.source_grid_power_entity)

        if soc is None or battery_power is None or raw_grid_power is None:
            _LOGGER.debug(
                "Inverter Control: insufficient control data soc=%s battery_power=%s grid_power=%s",
                soc,
                battery_power,
                raw_grid_power,
            )
            return None

        # The grid reading already includes what the battery delivers, so add
        # the battery power back to get the house load the battery must cover.
        # Battery power is positive while discharging, negative while charging.
        house_load = float(raw_grid_power) + float(battery_power)
        alpha = self._data.external_control_ema_alpha
        previous_filtered = self._data.last_inverter_control_filtered_load_w
        if previous_filtered is None:
            filtered_house_load = house_load
        else:
            filtered_house_load = alpha * house_load + (1 - alpha) * previous_filtered
        self._data.last_inverter_control_filtered_load_w = filtered_house_load

        return {
            "raw_grid_power": float(raw_grid_power),
            "battery_power": float(battery_power),
            "filtered_house_load": filtered_house_load,
        }

    def _clamp_target_watts(self, target_watts: float) -> float:
        """Cap the target by the configured maximum and the maximum battery control power.

        Without a configured maximum only the maximum battery control power
        applies; when that is unknown too, the inverter clamps the setpoint.
        """
        if target_watts > 0.0:
            cap = self._power_cap(self._data.external_control_max_discharge_w)
            return target_watts if cap is None else min(target_watts, cap)
        cap = self._power_cap(self._data.external_control_max_charge_w)
        return target_watts if cap is None else max(target_watts, -cap)

    def _power_cap(self, configured_w: float | None) -> float | None:
        caps = [c for c in (configured_w, self._data.max_battery_power_step_w()) if c is not None]
        return max(0.0, min(caps)) if caps else None

    def _grid_target_watts(self, inputs: dict[str, float]) -> tuple[float, str]:
        """Return the signed battery target (+ discharge, - charge) and a status."""
        filtered_house_load = inputs["filtered_house_load"]
        # Grid power as it would read with the smoothed load and today's battery output
        grid_error = filtered_house_load - inputs["battery_power"] - self._data.grid_target_w

        if abs(grid_error) <= self._data.grid_deadband_w:
            # Close enough — keep the battery where it is instead of dropping to 0,
            # which would just push the grid back out of the deadband
            last_target = self._data.last_inverter_control_setpoint_w
            held = inputs["battery_power"] if last_target is None else last_target
            return self._clamp_target_watts(held), "Grid Idle"

        return self._clamp_target_watts(filtered_house_load - self._data.grid_target_w), "Grid Support"

    def _smoothed_target_watts(self, proposed_watts: float) -> float:
        """Only move the setpoint when it changes by more than the hysteresis."""
        last_target = self._data.last_inverter_control_setpoint_w
        if last_target is None or abs(proposed_watts - last_target) > self._data.external_control_hysteresis_w:
            self._data.last_inverter_control_setpoint_w = proposed_watts
            return proposed_watts
        return last_target

    async def _loop_action(self, *args):
        if not self._attr_is_on:
            return
        # A grid update and the fallback timer can fire together — one
        # calculation at a time is enough
        if self._calculation_lock.locked():
            return
        async with self._calculation_lock:
            self._last_calculation = time.monotonic()
            await self._calculate_and_write()

    async def _calculate_and_write(self) -> None:
        # Read battery power fresh on every calculation. The coordinator only
        # refreshes it every LOOP_INTERVAL seconds, and a stale value next to a
        # fresh grid reading gives a wrong house load.
        battery_power = await self._data.handler.read_int16(REG_BATTERY_POWER)
        inputs = self._grid_inputs(battery_power)
        if inputs is None:
            self._publish_state("Unavailable")
            await self._write_power_setpoint(0.0)
            return

        filtered_house_load = inputs["filtered_house_load"]
        proposed_watts, status = self._grid_target_watts(inputs)
        target_watts = self._smoothed_target_watts(proposed_watts)
        self._publish_state(
            status,
            target_watts=target_watts,
            house_load_w=filtered_house_load,
        )
        _LOGGER.debug(
            "Inverter Control: raw_grid=%.1fW battery=%.1fW filtered_load=%.1fW grid_target=%.1fW proposed=%.1fW target=%.1fW status=%s",
            inputs["raw_grid_power"],
            inputs["battery_power"],
            filtered_house_load,
            self._data.grid_target_w,
            proposed_watts,
            target_watts,
            status,
        )
        await self._write_power_setpoint(target_watts)

    async def _stop_action(self):
        self._data.last_stop_time = time.time()
        await self._write_power_setpoint(0.0)
        self._data.last_inverter_control_setpoint_w = None
        self._data.last_inverter_control_filtered_load_w = None
        self._publish_state("Inactive")
        await self._data.handler.close()

    def _on_communication_fault(self) -> None:
        self._data.last_inverter_control_setpoint_w = None
        self._publish_state("Unavailable")


class KostalIOOutputSwitch(SwitchEntity, RestoreEntity):
    """Simple one-shot switch for I/O board outputs. Writes 1 on, 0 off."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_registry_enabled_default = False

    def __init__(self, data, entry_id: str, key: str, name: str, register: int) -> None:
        self._data = data
        self._entry_id = entry_id
        self._key = key
        self._register = register
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_name = name
        self._attr_is_on = False

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)})

    async def async_added_to_hass(self) -> None:
        """Restore last state after HA restart."""
        last = await self.async_get_last_state()
        if last is not None:
            self._attr_is_on = last.state == "on"
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._data.handler.write_register(self._register, 1)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._data.handler.write_register(self._register, 0)
        self._attr_is_on = False
        self.async_write_ha_state()
