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
    PREDBAT_CHARGE_START_DELTA,
    PREDBAT_HOLD_DELTA,
    REG_CHARGE_RATE,
    REG_DISCHARGE_RATE,
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
    SWITCH_PREDBAT_CONTROL,
    SWITCH_AUTO_RESUME_ON_RECOVERY,
    SWITCH_IO_OUTPUT_1,
    SWITCH_IO_OUTPUT_2,
    SWITCH_IO_OUTPUT_3,
    SWITCH_IO_OUTPUT_4,
    EMS_SAFETY_MARGIN,
    EMS_PHASE_VOLTAGE,
    SIGNAL_EMS_STATUS_UPDATED,
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
    
    predbat_switch = KostalPredbatControlSwitch(data, entry.entry_id)
    auto_resume_switch = KostalAutoResumeRecoverySwitch(data, entry.entry_id)
    charge_start_switch = KostalChargeStartSwitch(data, entry.entry_id, predbat_switch)
    discharge_start_switch = KostalDischargeStartSwitch(data, entry.entry_id)
    block_discharge_switch = KostalBlockDischargeSwitch(data, entry.entry_id)
    block_charge_switch = KostalBlockChargeSwitch(data, entry.entry_id)
    exclusive_switches = [
        charge_start_switch,
        discharge_start_switch,
        block_discharge_switch,
        block_charge_switch,
    ]
    for switch in exclusive_switches:
        switch.set_related_switches(exclusive_switches)

    entities = [
        charge_start_switch,
        discharge_start_switch,
        block_discharge_switch,
        block_charge_switch,
        KostalEMSSwitch(data, entry.entry_id, charge_start_switch),
        predbat_switch,
        auto_resume_switch,
        # I/O Board outputs (hidden by default)
        KostalIOOutputSwitch(data, entry.entry_id, SWITCH_IO_OUTPUT_1, "I/O Output 1", REG_IO_OUTPUT_1),
        KostalIOOutputSwitch(data, entry.entry_id, SWITCH_IO_OUTPUT_2, "I/O Output 2", REG_IO_OUTPUT_2),
        KostalIOOutputSwitch(data, entry.entry_id, SWITCH_IO_OUTPUT_3, "I/O Output 3", REG_IO_OUTPUT_3),
        KostalIOOutputSwitch(data, entry.entry_id, SWITCH_IO_OUTPUT_4, "I/O Output 4", REG_IO_OUTPUT_4),
    ]
    async_add_entities(entities)

class KostalBaseSwitch(SwitchEntity):
    """Base class for Kostal switches."""

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
        return self._auto_resume_on_recovery and self._data.auto_resume_on_recovery

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
            self.name,
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
        # så ingen Modbus-besked nulstiller inverterens 1034-timeout under ventetiden.
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
            return coordinator.data.get(REG_DISCHARGE_RATE) or 0.0
        return 0.0

    async def _restore_max_discharge_limit(self) -> bool:
        """Restore register 1040 to the battery's current maximum discharge limit."""
        max_discharge_watts = self._max_discharge_watts()
        if max_discharge_watts <= 0.0:
            _LOGGER.warning(
                "Predbat Control: cannot restore discharge limit because max discharge is unavailable"
            )
            return False

        await self._data.handler.write_float(REG_DISCHARGE_RATE, max_discharge_watts)
        return True

    def _stop_signed_pct_from_active_power(self) -> float:
        """Estimate a signed stop setpoint from grid-point power and battery power.

        For a smart meter at the grid connection point, register 252 is:
        - positive when importing from grid
        - negative when exporting to grid

        Battery power is:
        - negative while charging
        - positive while discharging

        Adding the two removes the battery contribution and gives an estimate of
        the underlying house demand seen at the grid point.

        Result:
        - positive setpoint when the house still needs battery discharge
        - negative setpoint when PV surplus is available for battery charge
        """
        coordinator = self._data.coordinator
        if coordinator is None or coordinator.data is None:
            _LOGGER.debug("Stop setpoint: no coordinator data available")
            return 0.0

        total_active_power = coordinator.data.get(REG_TOTAL_ACTIVE_POWER)
        battery_power = coordinator.data.get(REG_BATTERY_POWER)
        max_discharge_watts = self._max_discharge_watts()
        max_charge_watts = self._max_charge_watts()

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
        # then converted to a signed stop setpoint.
        net_load_after_pv_watts = total_active_power + battery_power

        if net_load_after_pv_watts >= 0.0:
            if max_discharge_watts <= 0.0:
                _LOGGER.debug(
                    "Stop setpoint: discharge max unavailable total_active_power=%s battery_power=%s max_discharge_watts=%s",
                    total_active_power,
                    battery_power,
                    max_discharge_watts,
                )
                return 0.0

            target_pct = min(100.0, (net_load_after_pv_watts / max_discharge_watts) * 100.0)
            signed_stop_pct = round(target_pct, 1)
        else:
            if max_charge_watts <= 0.0:
                _LOGGER.debug(
                    "Stop setpoint: charge max unavailable total_active_power=%s battery_power=%s max_charge_watts=%s",
                    total_active_power,
                    battery_power,
                    max_charge_watts,
                )
                return 0.0

            target_pct = min(100.0, (-net_load_after_pv_watts / max_charge_watts) * 100.0)
            signed_stop_pct = -round(target_pct, 1)

        _LOGGER.debug(
            "Stop setpoint: total_active_power=%.1fW battery_power=%.1fW net_load_after_pv=%.1fW max_charge=%.1fW max_discharge=%.1fW signed_stop_pct=%s%%",
            total_active_power,
            battery_power,
            net_load_after_pv_watts,
            max_charge_watts,
            max_discharge_watts,
            signed_stop_pct,
        )

        return signed_stop_pct

    async def _pre_start_action(self):
        """Køres straks ved start, inden eventuel ventetid på 1034."""
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

    def __init__(self, data, entry_id, predbat_switch=None):
        super().__init__(data, entry_id)
        self._predbat_switch = predbat_switch
        self._predbat_was_charging: bool | None = None
        self._predbat_transition_time: float | None = None
        self._predbat_startup_block_until: float | None = None
        self._predbat_discharge_blocked: bool = False

    def _set_predbat_status(self, status: str) -> None:
        if self._data.predbat_status == status:
            return

        self._data.predbat_status = status
        async_dispatcher_send(
            self.hass, f"{SIGNAL_PREDBAT_STATUS_UPDATED}_{self._entry_id}", status
        )

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

    def _predbat_charge_stop_pct(self) -> float:
        soc, charge_start_limit, hold_limit, should_charge_now = self._predbat_limit_decision()
        if should_charge_now is None:
            _LOGGER.warning(
                "Predbat Control: SOC=%s start_limit=%s hold_limit=%s unavailable during charge stop — using signed stop setpoint",
                soc,
                charge_start_limit,
                hold_limit,
            )
            return self._stop_signed_pct_from_active_power()

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

        signed_stop_pct = self._stop_signed_pct_from_active_power()
        _LOGGER.info(
            "Predbat Control: SOC=%.1f%% below active threshold (start_limit=%.1f%% hold_limit=%.1f%%) — using signed stop setpoint %s%%",
            soc,
            charge_start_limit,
            hold_limit,
            signed_stop_pct,
        )
        return signed_stop_pct

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self._predbat_switch is not None and self._predbat_switch.is_on:
            # self._predbat_startup_block_until = time.time() + 15.0
            self._predbat_startup_block_until = None
            _soc, _charge_start_limit, _hold_limit, should_charge_now = self._predbat_limit_decision()
            if should_charge_now is None:
                self._set_predbat_status("Waiting")
            elif should_charge_now:
                self._set_predbat_status("Charge")
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
        immediately. Reads may continue and writes to 1028 are no longer
        delayed during startup.
        """
        if self._predbat_switch is not None and self._predbat_switch.is_on:
            # Respect the same last_stop_time settling delay as the base class.
            # A previous switch (e.g. Discharge Start) may have written to 1028 recently.
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
                # 1028 not written — no transition wait needed
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
                _LOGGER.info(
                    "Predbat Control: startup decision = hold because SOC=%.1f%% is above charge_start_limit=%.1f%%",
                    soc,
                    charge_start_limit,
                )
                self._write_activity(
                    f"Predbat startup: hold because SOC={soc:.1f}% is above start limit {charge_start_limit:.1f}%"
                )
                # 1028 not written — inverter already in internal control, go directly to hold
                self._predbat_was_charging = False
                self._predbat_transition_time = None
                self._set_predbat_status("Hold")

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
        if self._predbat_switch is not None and self._predbat_switch.is_on:
            await self._predbat_loop_action()
        else:
            self._set_predbat_status("Inactive")
            # Normal charge — no Predbat Control
            target_pct = self._data.charge_rate
            if self._data.ems_status != "Inactive":
                target_pct = min(target_pct, self._data.ems_charge_limit_pct)
            await self._data.handler.write_float(self._data.charge_discharge_reg, -abs(target_pct))

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

        if should_charge_now:
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
            charge_pct = abs(self._data.charge_rate)
            if self._data.ems_status != "Inactive":
                charge_pct = min(charge_pct, self._data.ems_charge_limit_pct)
            if not self._attr_is_on:
                return
            if self._predbat_startup_write_blocked():
                return
            await self._data.handler.write_float(self._data.charge_discharge_reg, -charge_pct)
            return

        if self._predbat_was_charging is None:
            # 1028 was never written in this session — no transition wait needed
            self._predbat_was_charging = False
            self._predbat_transition_time = None

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
            signed_stop_pct = self._predbat_charge_stop_pct()
            await self._data.handler.write_float(self._data.charge_discharge_reg, signed_stop_pct)
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

        self._set_predbat_status("Hold")
        if soc <= hold_limit:
            # At/below hold limit — block discharge
            if not self._predbat_discharge_blocked:
                _LOGGER.info(
                    "Predbat Control: SOC=%.1f%% <= hold_limit=%.1f%% — blocking discharge",
                    soc, hold_limit,
                )
                self._write_activity(
                    f"Predbat hold: blocking discharge because SOC={soc:.1f}% <= hold limit {hold_limit:.1f}%"
                )
                self._predbat_discharge_blocked = True
            await self._data.handler.write_float(REG_DISCHARGE_RATE, 0.0)
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
        # Only write a signed stop setpoint to 1028 if we were actually charging.
        # In predbat hold mode (_predbat_was_charging is False), that stop
        # setpoint was already written when Predbat switched from charge to hold.
        # In normal mode (predbat switch OFF), we always write it here.
        if self._predbat_switch is None or not self._predbat_switch.is_on or self._predbat_was_charging is True:
            # Always use live power balance on manual stop — the 0.0 hold-transition
            # setpoint only makes sense when charge completes naturally in _predbat_loop_action.
            signed_stop_pct = self._stop_signed_pct_from_active_power()
            await self._data.handler.write_float(self._data.charge_discharge_reg, signed_stop_pct)
        self._data.last_stop_time = time.time()
        self._set_predbat_status("Inactive")
        if self._predbat_discharge_blocked:
            self._predbat_discharge_blocked = False
            await self._restore_max_discharge_limit()
        self._predbat_was_charging = None
        self._predbat_transition_time = None
        self._predbat_startup_block_until = None
        # Close the Modbus connection so the inverter sees a clean disconnect.
        # It will reconnect automatically on the next read/write.
        await self._data.handler.close()

    def _on_communication_fault(self) -> None:
        self._set_predbat_status("Inactive")

class KostalDischargeStartSwitch(KostalBaseSwitch):
    _key = SWITCH_DISCHARGE_START
    _name = "Discharge Start"
    _auto_resume_on_recovery = True

    async def _loop_action(self, *args):
        if not self._attr_is_on:
            return
        await self._data.handler.write_float(self._data.charge_discharge_reg, abs(self._data.discharge_rate))

    async def _stop_action(self):
        self._data.last_stop_time = time.time()
        # Recalculate the signed stop setpoint so the inverter can settle into
        # either discharge, neutral, or charge depending on live net power.
        signed_stop_pct = self._stop_signed_pct_from_active_power()
        await self._data.handler.write_float(self._data.charge_discharge_reg, signed_stop_pct)
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
        await self._data.handler.write_float(REG_DISCHARGE_RATE, 0.0)

    async def _stop_action(self):
        self._data.last_stop_time = time.time()
        await self._data.handler.write_float(REG_DISCHARGE_RATE, self._max_discharge_watts())
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
        await self._data.handler.write_float(REG_CHARGE_RATE, 0.0)

    async def _stop_action(self):
        self._data.last_stop_time = time.time()
        await self._data.handler.write_float(REG_CHARGE_RATE, self._max_charge_watts())
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

        headroom_watts = min(
            (safe_limit_amps - max(0.0, phase1)) * 3 * EMS_PHASE_VOLTAGE,
            (safe_limit_amps - max(0.0, phase2)) * 3 * EMS_PHASE_VOLTAGE,
            (safe_limit_amps - max(0.0, phase3)) * 3 * EMS_PHASE_VOLTAGE,
        )

        # Convert headroom watts → % using max of 1076/1078 as battery max power
        battery_voltage = data.get(REG_BATTERY_VOLTAGE) or 400.0
        max_charge_w = data.get(REG_BATTERY_MAX_CHARGE_LIMIT) or 0.0
        max_discharge_w = data.get(REG_BATTERY_MAX_DISCHARGE_LIMIT) or 0.0
        max_watts = max(max_charge_w, max_discharge_w)
        if max_watts <= 0.0:
            _LOGGER.warning("EMS: Battery max power unavailable (1076=%.0f, 1078=%.0f) — skipping cycle", max_charge_w, max_discharge_w)
            return

        prev_limit = self._ems_smoothed_limit if self._ems_smoothed_limit is not None else self._data.charge_rate
        raw_pct = max(0.0, min(prev_limit + (headroom_watts / max_watts * 100.0), self._data.charge_rate))

        EMA_ALPHA = 0.3
        if self._ems_smoothed_limit is None:
            self._ems_smoothed_limit = raw_pct
        else:
            self._ems_smoothed_limit = EMA_ALPHA * raw_pct + (1 - EMA_ALPHA) * self._ems_smoothed_limit

        target_pct = round(self._ems_smoothed_limit, 1)

        if target_pct == 0.0:
            new_status = "Blocked"
        elif target_pct < self._data.charge_rate:
            new_status = "Protecting"
        else:
            new_status = "Ok"

        _LOGGER.debug(
            "EMS: phase=%.1f/%.1f/%.1f A, fuse=%sA, headroom=%.0f W, max_batt=%.0fW → raw=%.1f%% smooth=%s%% (%s)",
            phase1, phase2, phase3, fuse_size,
            headroom_watts, max_watts,
            raw_pct, target_pct, new_status,
        )

        self._data.ems_charge_limit_pct = target_pct
        self._set_ems_status(new_status)
        # EMS does NOT write to Modbus — Charge Start is the sole writer to 1034

    async def _stop_action(self) -> None:
        self._ems_smoothed_limit = None
        self._data.ems_charge_limit_pct = 100.0
        self._set_ems_status("Inactive")
        # EMS does NOT write to Modbus — nothing is written unless a charge switch is active

    def _on_communication_fault(self) -> None:
        self._ems_smoothed_limit = None


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


class KostalAutoResumeRecoverySwitch(SwitchEntity, RestoreEntity):
    """Config switch to enable automatic resume for control switches after recovery."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _key = SWITCH_AUTO_RESUME_ON_RECOVERY
    _name = "Auto Resume On Recovery"

    def __init__(self, data, entry_id: str) -> None:
        self._data = data
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{self._key}"
        self._attr_name = self._name
        self._attr_is_on = bool(self._data.auto_resume_on_recovery)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry_id)})

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None:
            self._attr_is_on = last.state == "on"
        self._data.auto_resume_on_recovery = self._attr_is_on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self._data.auto_resume_on_recovery = True
        _LOGGER.info("Automatic resume after recovery enabled for control switches")
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self._data.auto_resume_on_recovery = False
        _LOGGER.info("Automatic resume after recovery disabled for control switches")
        self.async_write_ha_state()


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
