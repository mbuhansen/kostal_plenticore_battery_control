from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta
from functools import partial
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_UNIT_ID,
    DEFAULT_PORT,
    DEFAULT_UNIT_ID,
    DOMAIN,
    CONF_MODBUS_TIMEOUT,
    CONTROL_SETTLE_MARGIN_SECONDS,
    DEFAULT_MODBUS_TIMEOUT,
    LOOP_INTERVAL,
    REG_MODBUS_BYTE_ORDER,
    REG_INVERTER_STATE,
    REG_MODEL,
    REG_POWER_CLASS,
    REG_INVERTER_MAX_POWER,
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
    REG_BATTERY_DC_POWER_SETPOINT_W,
    REG_BATTERY_AC_POWER_SETPOINT_W,
    REG_BATTERY_MAX_CHARGE_POWER_W,
    REG_BATTERY_MAX_DISCHARGE_POWER_W,
    BATTERY_FULL_SOC,
    BATTERY_NOMINAL_CURRENT_BY_GENERATION,
    BI_NOMINAL_POWER_BY_POWER_CLASS,
    BATTERY_MAX_VOLTAGE_RANGE,
    KEY_BATTERY_MAX_VOLTAGE_SUNSPEC,
    MAX_POWER_SOURCE_LEARNED,
    MAX_POWER_SOURCE_SUNSPEC,
    SUNSPEC_BASE_ADDRESS,
    SUNSPEC_BATTERY_MODEL_ID,
    SUNSPEC_BATTERY_V_SF_OFFSET,
    SUNSPEC_BATTERY_VMAX_OFFSET,
    SUNSPEC_END_MODEL_ID,
    SUNSPEC_MARKER,
    SUNSPEC_MAX_MODELS,
    MAX_POWER_SOURCE_INVERTER_MAX_POWER,
    MAX_POWER_SOURCE_BATTERY_VOLTAGE,
    MAX_POWER_SOURCE_BI_POWER_CLASS,
    MAX_POWER_SOURCE_BI_DISCHARGE_LIMIT,
    STORAGE_VERSION,
    STORAGE_SAVE_DELAY_SECONDS,
    CONF_INVERTER_TYPE,
    INVERTER_TYPE_BI,
    REG_BATTERY_WORK_CAPACITY,
    REG_BATTERY_MGMT_MODE,
    REG_BATTERY_TYPE,
    REG_BATTERY_CURRENT,
    REG_BATTERY_CYCLES,
    REG_BATTERY_GROSS_CAPACITY,
    KEY_BATTERY_GROSS_CAPACITY,
    REG_BATTERY_MODEL_ID,
    REG_BATTERY_BMS_SERIAL,
    REG_BATTERY_FIRMWARE,
    REG_SOFTWARE_VERSION,
    SOFTWARE_VERSION_LENGTH,
    REST_VERSION_PATH,
    REST_VERSION_TIMEOUT_SECONDS,
    REST_VERSION_RETRY_SECONDS,
    BATTERY_TYPE_MAP,
    REG_BATTERY_MIN_SOC,
    REG_BATTERY_MAX_SOC,
    DEFAULT_MIN_SOC_LIMIT,
    MIN_SOC_LIMIT_RANGE,
    DEFAULT_MAX_SOC_LIMIT,
    DEFAULT_HOLD_SOC_OFFSET,
    HOLD_SOC_OFFSET_RANGE,
    CONF_HOLD_SOC_OFFSET,
    CONF_HOLD_USE_DISCHARGE_LIMIT,
    DEFAULT_HOLD_USE_DISCHARGE_LIMIT,
    DISCHARGE_LIMIT_GUARD_POWER_W,
    DISCHARGE_LIMIT_GUARD_SECONDS,
    POWER_RATE_FALLBACK_MAX_W,
    POWER_RATE_STEP_W,
    REG_CURRENT_PHASE1,
    REG_CURRENT_PHASE2,
    REG_CURRENT_PHASE3,
    REG_ACTIVE_POWER_PHASE1,
    REG_ACTIVE_POWER_PHASE2,
    REG_ACTIVE_POWER_PHASE3,
    REG_HOME_FROM_BATTERY_W,
    REG_HOME_FROM_GRID_W,
    REG_HOME_FROM_PV_W,
    REG_HOME_CONSUMPTION_TOTAL_WH,
    REG_PV_ENERGY_TOTAL_WH,
    REG_PV_POWER_W,
    REG_GRID_ENERGY_EXPORTED_WH,
    REG_GRID_ENERGY_IMPORTED_WH,
    REG_SENSOR_TYPE,
    CONF_KSEM_HOST,
    KSEM_PORT,
    KSEM_SLAVE_ID,
    REG_KSEM_ENERGY_IMPORTED,
    REG_KSEM_ENERGY_EXPORTED,
    REG_KSEM_GRID_POWER_TOTAL,
    REG_KSEM_SUM_OUTPUT_INVERTER_AC,
    REG_KSEM_SUM_PV_POWER_INVERTER_DC,
    REG_KSEM_HOME_CONSUMPTION,
    REG_KSEM_BATTERY_CHARGE_DISCHARGE_DC,
    REG_KSEM_SYSTEM_SOC,
    REG_KSEM_HOME_CONSUMPTION_FROM_PV,
    REG_KSEM_HOME_CONSUMPTION_FROM_BATTERY,
    REG_KSEM_HOME_CONSUMPTION_FROM_GRID,
    CONF_SOURCE_GRID_POWER_ENTITY,
    CONF_GRID_TARGET_W,
    CONF_GRID_DEADBAND_W,
    CONF_EXTERNAL_CONTROL_MAX_DISCHARGE_W,
    CONF_EXTERNAL_CONTROL_MAX_CHARGE_W,
    CONF_EXTERNAL_CONTROL_HYSTERESIS_W,
    CONF_EXTERNAL_CONTROL_EMA_ALPHA,
    DEFAULT_GRID_TARGET_W,
    DEFAULT_GRID_DEADBAND_W,
    DEFAULT_EXTERNAL_CONTROL_HYSTERESIS_W,
    DEFAULT_EXTERNAL_CONTROL_EMA_ALPHA,
    MIN_EXTERNAL_CONTROL_EMA_ALPHA,
)
from .modbus_handler import KostalModbusHandler, KostalModbusRequestError

_LOGGER = logging.getLogger(__name__)


class KostalCoordinator(DataUpdateCoordinator[dict[Any, Any]]):
    """Coordinator that batches all sensor reads into a single update cycle.

    Values are keyed by register address, except where two devices share an
    address — see KEY_BATTERY_GROSS_CAPACITY.
    """

    def __init__(
        self, hass: HomeAssistant, handler: KostalModbusHandler, kostal_data: "KostalData", host: str
    ) -> None:
        super().__init__(
            hass,
            logging.getLogger(f"{__name__}.coordinator"),
            name=DOMAIN,
            update_interval=timedelta(seconds=LOOP_INTERVAL),
        )
        self._handler = handler
        self._kostal_data = kostal_data
        # Registers this inverter answered "no such address" for. Not every
        # Plenticore implements every documented register, so they are read
        # once and then skipped for the life of the entry.
        self._unsupported: set = set()
        self._sunspec_battery_model_address: int | None = None
        self._host = host
        # Software version from the REST API, used only when register 58 is
        # refused. Fetched once per connection — see _async_rest_software_version.
        self._rest_version: str | None = None
        self._rest_version_next_try = 0.0
        self._rest_version_logged_failure = False
        # Values that only change with a battery swap or a firmware update —
        # both restart the inverter, i.e. a communication outage. Read once per
        # connection rather than on every poll; None means "read on next poll".
        self._static_data: dict | None = None

    async def _read_optional(self, key, description, read):
        """Read a register that some inverter models may not implement.

        An "illegal data address" reply is the inverter telling us the register
        does not exist on this firmware — record that, skip it from then on and
        carry on with the rest of the update. Timeouts and transport errors are
        left to propagate: those really do mean the inverter is unreachable.
        """
        if key in self._unsupported:
            return None
        try:
            return await read()
        except KostalModbusRequestError as err:
            self._unsupported.add(key)
            _LOGGER.info(
                "This inverter does not implement %s — it will be skipped from now on (%s)",
                description,
                err,
            )
            return None

    async def _async_find_sunspec_battery_model(self) -> int | None:
        """Walk the SunSpec model list and return the address of the battery model, or None."""
        if await self._handler.read_uint32_big_endian(SUNSPEC_BASE_ADDRESS) != SUNSPEC_MARKER:
            return None
        address = SUNSPEC_BASE_ADDRESS + 2
        for _ in range(SUNSPEC_MAX_MODELS):
            model_id = await self._handler.read_uint16(address)
            if model_id == SUNSPEC_END_MODEL_ID:
                return None
            length = await self._handler.read_uint16(address + 1)
            if model_id == SUNSPEC_BATTERY_MODEL_ID:
                return address if length > SUNSPEC_BATTERY_V_SF_OFFSET else None
            address += 2 + length
        return None

    async def _async_read_sunspec_battery_max_voltage(self) -> float | None:
        """Battery maximum voltage from SunSpec model 802, or None when it is not usable."""
        if self._sunspec_battery_model_address is None:
            self._sunspec_battery_model_address = await self._async_find_sunspec_battery_model()
            if self._sunspec_battery_model_address is None:
                self._unsupported.add(KEY_BATTERY_MAX_VOLTAGE_SUNSPEC)
                _LOGGER.info("This inverter has no SunSpec battery model — the battery maximum voltage is learned instead")
                return None
        first_point = self._sunspec_battery_model_address + 2
        raw = await self._handler.read_uint16(first_point + SUNSPEC_BATTERY_VMAX_OFFSET)
        scale = await self._handler.read_int16(first_point + SUNSPEC_BATTERY_V_SF_OFFSET)
        if not -10 <= scale <= 10:
            return None
        voltage = round(raw * 10.0**scale, 3)
        return voltage if BATTERY_MAX_VOLTAGE_RANGE[0] <= voltage <= BATTERY_MAX_VOLTAGE_RANGE[1] else None

    async def _async_rest_software_version(self) -> str | None:
        """UI software version from the inverter's REST API.

        Only used when the inverter refuses register 58. The web API reports the
        same version without logging in, and it only changes with a firmware
        update — which restarts the inverter, i.e. a communication outage — so
        it is fetched once per connection rather than on every poll. A failed
        fetch is retried after REST_VERSION_RETRY_SECONDS, and the last known
        version is kept in the meantime.
        """
        now = time.monotonic()
        if now < self._rest_version_next_try:
            return self._rest_version
        url = f"http://{self._host}{REST_VERSION_PATH}"
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=REST_VERSION_TIMEOUT_SECONDS)
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
            version = payload.get("sw_version") if isinstance(payload, dict) else None
            if not version:
                raise ValueError(f"no sw_version in {payload!r}")
        except Exception as err:
            self._rest_version_next_try = now + REST_VERSION_RETRY_SECONDS
            log = _LOGGER.debug if self._rest_version_logged_failure else _LOGGER.info
            log(
                "Could not read the software version from %s, retrying later: %s %s",
                url,
                type(err).__name__,
                err,
            )
            self._rest_version_logged_failure = True
            return self._rest_version

        self._rest_version = str(version).strip()
        self._rest_version_next_try = float("inf")
        self._rest_version_logged_failure = False
        _LOGGER.debug("Software version %s read from %s", self._rest_version, url)
        return self._rest_version

    async def _async_read_static_data(self) -> dict:
        """Read the registers that do not change while the inverter runs."""
        data: dict = {}
        for key, description, read in (
            (REG_SENSOR_TYPE, "sensor type", partial(self._handler.read_uint8, REG_SENSOR_TYPE)),
            # The battery info block is big-endian regardless of the inverter's
            # byte-order setting, unlike the floats and the state register
            (
                KEY_BATTERY_GROSS_CAPACITY,
                "battery gross capacity",
                partial(self._handler.read_uint32_big_endian, REG_BATTERY_GROSS_CAPACITY),
            ),
            (
                REG_BATTERY_MODEL_ID,
                "battery model ID",
                partial(self._handler.read_uint32_big_endian, REG_BATTERY_MODEL_ID),
            ),
            (
                REG_BATTERY_BMS_SERIAL,
                "battery BMS serial",
                partial(self._handler.read_uint32_big_endian, REG_BATTERY_BMS_SERIAL),
            ),
            (
                REG_BATTERY_FIRMWARE,
                "battery firmware",
                partial(self._handler.read_uint32_big_endian, REG_BATTERY_FIRMWARE),
            ),
            # U16 register
            (REG_BATTERY_TYPE, "battery type", partial(self._handler.read_uint16, REG_BATTERY_TYPE)),
            # String register — byte order is fixed, no word swap involved.
            # PLENTICORE plus G1 does not implement this one at all.
            (
                REG_SOFTWARE_VERSION,
                f"the software version register {REG_SOFTWARE_VERSION}",
                partial(self._handler.read_string, REG_SOFTWARE_VERSION, SOFTWARE_VERSION_LENGTH),
            ),
        ):
            data[key] = await self._read_optional(key, description, read)
        if not self._kostal_data.is_battery_inverter:
            data[KEY_BATTERY_MAX_VOLTAGE_SUNSPEC] = await self._read_optional(
                KEY_BATTERY_MAX_VOLTAGE_SUNSPEC,
                "the SunSpec battery model",
                self._async_read_sunspec_battery_max_voltage,
            )
        return data

    async def _async_update_data(self) -> dict:
        try:
            # First poll after an outage: re-probe everything. A register refused
            # while the inverter was rebooting is not necessarily missing, and a
            # transient must never disable an entity for the rest of the session.
            # Costs one failed read per genuinely absent register per reconnect.
            if not self._kostal_data.communication_ok and self._unsupported:
                _LOGGER.debug(
                    "Communication was lost — re-probing %d previously unsupported register(s)",
                    len(self._unsupported),
                )
                self._unsupported.clear()
            if not self._kostal_data.communication_ok:
                # A firmware update restarts the inverter, so fetch the REST
                # version again once the connection is back
                self._rest_version_next_try = 0.0
                # So does the model list, which a firmware update can change
                self._sunspec_battery_model_address = None
                # And every other static value, which a battery swap or a
                # firmware update — each an outage — can change
                self._static_data = None
            if self._static_data is None:
                self._static_data = await self._async_read_static_data()
            data: dict = dict(self._static_data)
            # Float registers (2 registers each)
            for address in (
                REG_TOTAL_ACTIVE_POWER,
                REG_VOLTAGE_PHASE1,
                REG_VOLTAGE_PHASE2,
                REG_VOLTAGE_PHASE3,
                REG_BATTERY_SOC,
                REG_BATTERY_VOLTAGE,
                REG_BATTERY_TEMP,
                REG_BATTERY_MAX_CHARGE_LIMIT,
                REG_BATTERY_MAX_DISCHARGE_LIMIT,
                REG_BATTERY_DC_POWER_SETPOINT_W,
                REG_BATTERY_AC_POWER_SETPOINT_W,
                REG_BATTERY_MAX_CHARGE_POWER_W,
                REG_BATTERY_MAX_DISCHARGE_POWER_W,
                REG_BATTERY_WORK_CAPACITY,
                REG_BATTERY_CURRENT,
                REG_BATTERY_CYCLES,
                REG_BATTERY_MIN_SOC,
                REG_BATTERY_MAX_SOC,
                REG_CURRENT_PHASE1,
                REG_CURRENT_PHASE2,
                REG_CURRENT_PHASE3,
                REG_ACTIVE_POWER_PHASE1,
                REG_ACTIVE_POWER_PHASE2,
                REG_ACTIVE_POWER_PHASE3,
                REG_HOME_FROM_BATTERY_W,
                REG_HOME_FROM_GRID_W,
                REG_HOME_FROM_PV_W,
                REG_HOME_CONSUMPTION_TOTAL_WH,
                REG_PV_ENERGY_TOTAL_WH,
                REG_PV_POWER_W,
            ):
                data[address] = await self._read_optional(
                    address,
                    f"register {address}",
                    partial(self._handler.read_float, address),
                )
            for key, description, read in (
                # S16 register (1 register, signed int)
                (REG_BATTERY_POWER, "battery power", partial(self._handler.read_int16, REG_BATTERY_POWER)),
                # U8 register
                (REG_BATTERY_MGMT_MODE, "battery management mode", partial(self._handler.read_uint8, REG_BATTERY_MGMT_MODE)),
                # U32 register
                (REG_INVERTER_STATE, "inverter state", partial(self._handler.read_uint32, REG_INVERTER_STATE)),
                # Grid energy from the inverter's meter model, big-endian like SunSpec
                (
                    REG_GRID_ENERGY_IMPORTED_WH,
                    "grid energy imported",
                    partial(self._handler.read_uint32_big_endian, REG_GRID_ENERGY_IMPORTED_WH),
                ),
                (
                    REG_GRID_ENERGY_EXPORTED_WH,
                    "grid energy exported",
                    partial(self._handler.read_uint32_big_endian, REG_GRID_ENERGY_EXPORTED_WH),
                ),
            ):
                data[key] = await self._read_optional(key, description, read)
            # Register 58 refused: the REST fallback keeps its own retry timer
            # and returns the cached version in between, so ask it every poll
            if REG_SOFTWARE_VERSION in self._unsupported:
                data[REG_SOFTWARE_VERSION] = await self._async_rest_software_version()
            self._kostal_data.update_observed_battery_current(data)
            self._kostal_data.observe_inverter_min_soc(data.get(REG_BATTERY_MIN_SOC))
            # KSEM energy registers (separate handler, optional)
            ksem = self._kostal_data.ksem_handler
            if ksem is not None:
                for reg, label in (
                    (REG_KSEM_ENERGY_IMPORTED, "KSEM energy imported"),
                    (REG_KSEM_ENERGY_EXPORTED, "KSEM energy exported"),
                    (REG_KSEM_GRID_POWER_TOTAL, "KSEM grid power total"),
                    (REG_KSEM_SUM_OUTPUT_INVERTER_AC, "KSEM sum output inverter AC"),
                    (REG_KSEM_SUM_PV_POWER_INVERTER_DC, "KSEM sum PV power inverter DC"),
                    (REG_KSEM_HOME_CONSUMPTION, "KSEM home consumption"),
                    (REG_KSEM_BATTERY_CHARGE_DISCHARGE_DC, "KSEM battery charge/discharge DC"),
                ):
                    try:
                        if reg in (REG_KSEM_ENERGY_IMPORTED, REG_KSEM_ENERGY_EXPORTED):
                            data[reg] = await ksem.read_int64(reg)
                        else:
                            data[reg] = await ksem.read_int32(reg)
                    except Exception as err:
                        _LOGGER.debug("Failed to read %s: %s", label, err)
                        data[reg] = None
                try:
                    data[REG_KSEM_SYSTEM_SOC] = await ksem.read_uint16(REG_KSEM_SYSTEM_SOC)
                except Exception as err:
                    _LOGGER.debug("Failed to read KSEM system SoC: %s", err)
                    data[REG_KSEM_SYSTEM_SOC] = None
                for reg, label in (
                    (REG_KSEM_HOME_CONSUMPTION_FROM_PV, "KSEM home consumption from PV"),
                    (REG_KSEM_HOME_CONSUMPTION_FROM_BATTERY, "KSEM home consumption from battery"),
                    (REG_KSEM_HOME_CONSUMPTION_FROM_GRID, "KSEM home consumption from grid"),
                ):
                    try:
                        data[reg] = await ksem.read_uint32(reg)
                    except Exception as err:
                        _LOGGER.debug("Failed to read %s: %s", label, err)
                        data[reg] = None
            recovered = self._kostal_data.mark_communication_restored()
            if recovered:
                _LOGGER.info("Communication with Kostal inverter restored")
                self._kostal_data.notify_connection_restored()
            return data
        except Exception as err:
            self._kostal_data.mark_communication_lost(str(err))
            raise UpdateFailed(f"Error communicating with Kostal inverter: {err}") from err


PLATFORMS: list[Platform] = [Platform.SWITCH, Platform.NUMBER, Platform.SENSOR, Platform.BUTTON]

@dataclass
class KostalData:
    handler: KostalModbusHandler
    coordinator: KostalCoordinator | None = None
    # User-set charge/discharge rates in Watts. None means the rate follows the
    # maximum battery control power — see charge_power_w().
    charge_power_fixed_w: float | None = None
    discharge_power_fixed_w: float | None = None
    fuse_size: float = 25.0
    last_stop_time: float = 0.0
    inverter_timeout: int = DEFAULT_MODBUS_TIMEOUT
    ems_status: str = "Inactive"
    ems_charge_limit_w: float | None = None
    predbat_status: str = "Inactive"
    inverter_model: str = ""
    inverter_power_class: str = ""
    # Inverter max power (531) in W, None when the inverter lacks it
    inverter_max_power_w: float | None = None
    # Absolute power setpoint register: 1034 (DC) for hybrid, 1026 (AC) for BI
    charge_discharge_reg: int = REG_BATTERY_DC_POWER_SETPOINT_W
    # Highest 1078 / battery voltage and highest battery voltage seen, and the
    # battery's maximum voltage learned at a full charge — see
    # max_battery_power(). Kept across restarts in store.
    battery_nominal_current_observed: float | None = None
    battery_voltage_peak: float | None = None
    battery_max_voltage_learned: float | None = None
    battery_max_voltage_learned_at: str | None = None
    store: Store | None = None
    scaling_warnings_logged: set[str] = field(default_factory=set)
    # User setpoints from the SOC limit numbers. The defaults equal the
    # inverter's own limits, i.e. "not in use". The number entities own the
    # register writes — see KostalSocLimitNumber in number.py.
    min_soc: float = DEFAULT_MIN_SOC_LIMIT
    # The inverter's own min SOC (set in its web UI, which may also raise it to
    # protect the battery), read from 1042 while nothing is written. Every min
    # SOC the integration writes is at least this — see min_soc_floor.
    inverter_min_soc: float | None = None
    # Min SOC a discharge hold asks for (Block Discharge or Predbat's reserve
    # hold), None when no hold is active — see KostalBaseSwitch._hold_discharge_at
    discharge_hold_min_soc: float | None = None
    # Points added on top of every discharge hold's SOC (options flow) — see hold_min_soc
    hold_soc_offset: float = DEFAULT_HOLD_SOC_OFFSET
    # Holds block 1040 instead of writing 1042 (options flow)
    hold_use_discharge_limit: bool = DEFAULT_HOLD_USE_DISCHARGE_LIMIT
    # A hold has written 1040 = 0 and it has not been restored yet
    discharge_limit_blocked: bool = False
    # While 1040 is blocked: when the battery was first seen delivering power anyway,
    # and the min SOC the guard holds once that has lasted — see _update_limit_guard
    discharge_limit_delivering_since: float | None = None
    discharge_limit_guard_soc: float | None = None
    max_soc: float = DEFAULT_MAX_SOC_LIMIT
    auto_resume_on_recovery: bool = True
    communication_ok: bool = True
    last_error: str | None = None
    control_fault_latched: bool = False
    ksem_handler: KostalModbusHandler | None = None
    runtime_switches: dict[str, Any] = field(default_factory=dict)
    resume_pending_switches: set[str] = field(default_factory=set)
    # Grid control from an external grid-power entity (options flow)
    source_grid_power_entity: str | None = None
    grid_target_w: float = DEFAULT_GRID_TARGET_W
    grid_deadband_w: float = DEFAULT_GRID_DEADBAND_W
    # None = follow the maximum battery control power
    external_control_max_discharge_w: float | None = None
    external_control_max_charge_w: float | None = None
    external_control_hysteresis_w: float = DEFAULT_EXTERNAL_CONTROL_HYSTERESIS_W
    external_control_ema_alpha: float = DEFAULT_EXTERNAL_CONTROL_EMA_ALPHA
    last_inverter_control_setpoint_w: float | None = None
    last_inverter_control_filtered_load_w: float | None = None
    inverter_control_status: str = "Inactive"
    inverter_control_target_w: float | None = None
    inverter_control_house_load_w: float | None = None

    def register_runtime_switch(self, switch: Any) -> None:
        self.runtime_switches[switch._key] = switch

    @property
    def is_battery_inverter(self) -> bool:
        """True for a PLENTICORE BI, which is controlled through the AC setpoint."""
        return self.charge_discharge_reg == REG_BATTERY_AC_POWER_SETPOINT_W

    def _warn_once(self, key: str, message: str, *args: Any) -> None:
        if key in self.scaling_warnings_logged:
            return
        self.scaling_warnings_logged.add(key)
        _LOGGER.warning(message, *args)

    def update_observed_battery_current(self, data: dict) -> None:
        """Track the battery current and voltage the maximum control power is based on.

        Keeps the highest 1078 / battery voltage (the nominal battery current,
        only used when the inverter generation is unknown), the highest battery
        voltage, and the highest battery voltage at a full charge, which is
        taken as the battery's maximum voltage. Saved when one of them rises.
        """
        voltage = data.get(REG_BATTERY_VOLTAGE)
        if not voltage or voltage <= 0.0:
            return
        changed = False

        if self.battery_voltage_peak is None or voltage > self.battery_voltage_peak:
            self.battery_voltage_peak = voltage
            changed = True

        soc = data.get(REG_BATTERY_SOC)
        learned = self.battery_max_voltage_learned
        if soc is not None and soc >= BATTERY_FULL_SOC and (learned is None or voltage > learned):
            if learned is None:
                _LOGGER.info(
                    "Battery maximum voltage learned at %.0f%% SOC: %.1f V — the maximum battery control power "
                    "is now based on it instead of the power class",
                    soc,
                    voltage,
                )
            else:
                _LOGGER.debug("Battery maximum voltage raised from %.1f V to %.1f V", learned, voltage)
            self.battery_max_voltage_learned = voltage
            self.battery_max_voltage_learned_at = dt_util.utcnow().isoformat()
            changed = True

        max_discharge = data.get(REG_BATTERY_MAX_DISCHARGE_LIMIT)
        if max_discharge and max_discharge > 0.0:
            current = max_discharge / voltage
            observed = self.battery_nominal_current_observed
            if observed is None or current > observed:
                self.battery_nominal_current_observed = current
                _LOGGER.debug("Observed nominal battery current %.2f A (1078=%.0f W, V=%.1f V)", current, max_discharge, voltage)
                changed = True

        if changed and self.store is not None:
            self.store.async_delay_save(self._storage_data, STORAGE_SAVE_DELAY_SECONDS)

    def _storage_data(self) -> dict[str, Any]:
        return {
            "battery_nominal_current_observed": self.battery_nominal_current_observed,
            "battery_voltage_peak": self.battery_voltage_peak,
            "battery_max_voltage_learned": self.battery_max_voltage_learned,
            "battery_max_voltage_learned_at": self.battery_max_voltage_learned_at,
            "inverter_min_soc": self.inverter_min_soc,
        }

    def load_storage_data(self, stored: dict[str, Any] | None) -> None:
        """Restore the values saved by update_observed_battery_current()."""
        if not stored:
            return
        self.battery_nominal_current_observed = stored.get("battery_nominal_current_observed")
        self.battery_voltage_peak = stored.get("battery_voltage_peak")
        self.battery_max_voltage_learned = stored.get("battery_max_voltage_learned")
        self.battery_max_voltage_learned_at = stored.get("battery_max_voltage_learned_at")
        self.inverter_min_soc = stored.get("inverter_min_soc")

    def observe_inverter_min_soc(self, value: float | None) -> bool:
        """Learn the inverter's own min SOC from 1042, once nothing has been written for a while.

        Any write keeps the inverter in external control, where 1042 still shows
        the last value written, so it only shows the inverter's own setting once
        the timeout has expired. Returns True when the learned value changed.
        """
        if value is None or not MIN_SOC_LIMIT_RANGE[0] <= value <= MIN_SOC_LIMIT_RANGE[1]:
            return False
        if time.time() - self.handler.last_write_time < self.control_settle_seconds():
            return False
        value = round(value, 1)
        if self.inverter_min_soc == value:
            return False
        _LOGGER.info(
            "Inverter's own minimum SOC is %.0f%% (was %s) — the integration never writes a lower min SOC",
            value,
            "unknown" if self.inverter_min_soc is None else f"{self.inverter_min_soc:.0f}%",
        )
        self.inverter_min_soc = value
        if self.store is not None:
            self.store.async_delay_save(self._storage_data, STORAGE_SAVE_DELAY_SECONDS)
        return True

    def min_soc_floor(self) -> float:
        """Lowest min SOC the integration writes: the inverter's own, or 5 % while it is unknown."""
        if self.inverter_min_soc is None:
            return DEFAULT_MIN_SOC_LIMIT
        return max(DEFAULT_MIN_SOC_LIMIT, self.inverter_min_soc)

    def documented_battery_nominal_current(self) -> float | None:
        """Documented nominal battery current of the inverter generation, or None when unknown."""
        if self.coordinator is None or self.coordinator.data is None:
            return None
        version = self.coordinator.data.get(REG_SOFTWARE_VERSION)
        if not version:
            return None
        try:
            current = BATTERY_NOMINAL_CURRENT_BY_GENERATION.get(int(str(version).strip().split(".")[0]))
        except ValueError:
            current = None
        if current is None:
            self._warn_once(
                f"version:{version}",
                "Unknown inverter generation for software version %r — the maximum battery control power "
                "uses the observed battery current",
                version,
            )
        return current

    def battery_nominal_current(self) -> float | None:
        """Documented nominal battery current, or the observed one when the generation is unknown.

        The observed current is only a fallback: a BMS derating at a low state
        of charge lowers 1078, so it can be below the inverter's real current.
        """
        documented = self.documented_battery_nominal_current()
        return documented if documented is not None else self.battery_nominal_current_observed

    def max_battery_power(self) -> tuple[float | None, str | None]:
        """Maximum battery control power in Watts and what it is based on.

        Hybrid: the nominal battery current times the battery's maximum voltage,
        reported through SunSpec or else learned at a full charge. Until it is
        learned the inverter max power (531), or the current times the highest
        battery voltage seen when 531 is unknown. BI: the nominal AC power from the power class, or the battery's
        discharge limit 1078 when the power class is unknown.
        """
        data = self.coordinator.data if self.coordinator is not None else None
        if data is None:
            return None, None

        if self.is_battery_inverter:
            power_class = (self.inverter_power_class or "").strip()
            match = re.search(r"\d+(?:[.,]\d+)?", power_class)
            if match is not None:
                nominal_power = BI_NOMINAL_POWER_BY_POWER_CLASS.get(float(match.group().replace(",", ".")))
                if nominal_power is not None:
                    return nominal_power, MAX_POWER_SOURCE_BI_POWER_CLASS
            self._warn_once(
                f"power_class:{power_class}",
                "Unknown PLENTICORE BI power class %r — using the battery discharge limit 1078 as maximum power",
                power_class,
            )
            max_discharge = data.get(REG_BATTERY_MAX_DISCHARGE_LIMIT)
            if max_discharge and max_discharge > 0.0:
                return max_discharge, MAX_POWER_SOURCE_BI_DISCHARGE_LIMIT
            return None, None

        current = self.battery_nominal_current()
        reported_voltage = data.get(KEY_BATTERY_MAX_VOLTAGE_SUNSPEC)
        if current is not None and reported_voltage is not None:
            return current * reported_voltage, MAX_POWER_SOURCE_SUNSPEC
        if current is not None and self.battery_max_voltage_learned is not None:
            return current * self.battery_max_voltage_learned, MAX_POWER_SOURCE_LEARNED
        if self.inverter_max_power_w:
            return self.inverter_max_power_w, MAX_POWER_SOURCE_INVERTER_MAX_POWER
        voltages = [v for v in (data.get(REG_BATTERY_VOLTAGE), self.battery_voltage_peak) if v and v > 0.0]
        if current is None or not voltages:
            return None, None
        return current * max(voltages), MAX_POWER_SOURCE_BATTERY_VOLTAGE

    def battery_max_voltage_sunspec(self) -> float | None:
        """Battery maximum voltage the inverter reports through SunSpec, or None."""
        data = self.coordinator.data if self.coordinator is not None else None
        return data.get(KEY_BATTERY_MAX_VOLTAGE_SUNSPEC) if data else None

    def battery_max_voltage(self) -> float | None:
        """Battery maximum voltage in use: the reported one, or else the learned one."""
        reported = self.battery_max_voltage_sunspec()
        return reported if reported is not None else self.battery_max_voltage_learned

    def max_battery_power_w(self) -> float | None:
        """Maximum battery control power in Watts, or None when it cannot be determined."""
        return self.max_battery_power()[0]

    def max_battery_power_step_w(self) -> float | None:
        """Maximum battery control power rounded up to a whole rate step (100 W).

        Rounding up means a rate that follows the maximum always asks for at
        least the full nominal battery current; the inverter clamps a setpoint
        above its limit itself.
        """
        max_power = self.max_battery_power_w()
        if max_power is None:
            return None
        return math.ceil(max_power / POWER_RATE_STEP_W) * POWER_RATE_STEP_W

    def charge_power_w(self) -> float:
        """Charge rate in Watts: the user's fixed value, or the maximum control power."""
        return self._power_rate_w(self.charge_power_fixed_w)

    def discharge_power_w(self) -> float:
        """Discharge rate in Watts: the user's fixed value, or the maximum control power."""
        return self._power_rate_w(self.discharge_power_fixed_w)

    def _power_rate_w(self, fixed_w: float | None) -> float:
        if fixed_w is not None:
            return fixed_w
        max_power = self.max_battery_power_step_w()
        if max_power is None:
            self._warn_once(
                "max_power_unknown",
                "Maximum battery control power is not known yet — using %.0f W and letting the inverter clamp it",
                POWER_RATE_FALLBACK_MAX_W,
            )
            return POWER_RATE_FALLBACK_MAX_W
        return max_power

    def clamp_power_setpoint_w(self, watts: float) -> float:
        """Clamp a signed power setpoint to plus/minus the maximum control power, rounded up to a rate step."""
        max_power = self.max_battery_power_step_w()
        if max_power is None:
            return watts
        return max(-max_power, min(max_power, watts))

    def hold_min_soc(self, soc_percent: float) -> float:
        """Min SOC a discharge hold at soc_percent writes: soc_percent + the hold offset, at most 100 %."""
        return min(100.0, soc_percent + self.hold_soc_offset)

    def effective_min_soc(self) -> float:
        """Min SOC for 1042: the inverter's own, the user's limit or a discharge hold, whichever is highest.

        A hold on 1040 leaves 1042 to the user's limit, unless its guard is active.
        With nothing in use this is the inverter's own min SOC, so a release never
        writes a lower one.
        """
        value = max(self.min_soc_floor(), self.min_soc)
        if self.hold_use_discharge_limit:
            if self.discharge_limit_guard_soc is None:
                return value
            return max(value, self.discharge_limit_guard_soc)
        if self.discharge_hold_min_soc is None:
            return value
        return max(value, self.discharge_hold_min_soc)

    async def async_write_min_soc(self) -> None:
        """Write effective_min_soc() to 1042."""
        await self.handler.write_float(REG_BATTERY_MIN_SOC, self.effective_min_soc())

    async def async_restore_discharge_limit(self) -> None:
        """Write the battery's maximum back to 1040 if a hold blocked it, or if it reads as blocked."""
        data = self.coordinator.data if self.coordinator is not None else None
        current_limit = data.get(REG_BATTERY_MAX_DISCHARGE_POWER_W) if data else None
        if not self.discharge_limit_blocked and (current_limit is None or current_limit > 0.0):
            return
        # 1078 follows the BMS, which throttles at low SoC or in the cold. A value read
        # then would stay in 1040 for as long as another keep-alive runs, so write the
        # higher of it and the maximum control power.
        battery_limit = data.get(REG_BATTERY_MAX_DISCHARGE_LIMIT) if data else None
        max_discharge = max((v for v in (battery_limit, self.max_battery_power_w()) if v), default=None)
        if max_discharge is None:
            _LOGGER.warning("Discharge hold: cannot restore 1040 because the maximum discharge power is unknown")
            return
        try:
            await self.handler.write_float(REG_BATTERY_MAX_DISCHARGE_POWER_W, max_discharge)
        except Exception:
            if not battery_limit or battery_limit == max_discharge:
                raise
            await self.handler.write_float(REG_BATTERY_MAX_DISCHARGE_POWER_W, battery_limit)
        self.discharge_limit_blocked = False

    async def async_write_discharge_hold(self, soc_percent: float) -> None:
        """Stop discharging at soc_percent, through 1040 or, with the option off, 1042.

        Since the firmware of October 2026, 1040 = 0 still lets the inverter's own
        standby draw come from the battery, while a min SOC at or above the SoC stops
        discharge at 0 A — see _update_limit_guard. 1040 has no SOC of its own, so it
        is only blocked once the SoC is down at soc_percent. Charging is not affected
        either way. Must be written continuously, like every battery register.
        """
        self.discharge_hold_min_soc = soc_percent
        if not self.hold_use_discharge_limit:
            await self.async_write_min_soc()
            return
        data = self.coordinator.data if self.coordinator is not None else None
        soc = data.get(REG_BATTERY_SOC) if data else None
        if soc is not None and soc > soc_percent:
            try:
                await self.async_restore_discharge_limit()
            finally:
                await self._async_clear_limit_guard()
            return
        # Before the write, so a failed write is still restored on release
        self.discharge_limit_blocked = True
        await self.handler.write_float(REG_BATTERY_MAX_DISCHARGE_POWER_W, 0.0)
        self._update_limit_guard(soc, data.get(REG_BATTERY_POWER) if data else None)
        if self.discharge_limit_guard_soc is not None:
            await self.async_write_min_soc()

    def _update_limit_guard(self, soc: float | None, battery_power: float | None) -> None:
        """Add the min SOC to a 1040 hold when the battery keeps delivering power.

        Once active it stays until the hold ends or the SoC is above it, because the
        min SOC then stops the battery and the power reading no longer shows why it
        was needed. It follows a rising SoC, so PV can charge, and never goes down.
        It holds the SoC and not the hold's target: a min SOC above the SoC can make
        the inverter drop out of FeedIn.
        """
        if self.discharge_limit_guard_soc is not None:
            if soc is not None:
                self.discharge_limit_guard_soc = max(self.discharge_limit_guard_soc, soc)
            return
        if soc is None or battery_power is None or battery_power <= DISCHARGE_LIMIT_GUARD_POWER_W:
            self.discharge_limit_delivering_since = None
            return
        now = time.time()
        if self.discharge_limit_delivering_since is None:
            self.discharge_limit_delivering_since = now
            return
        if now - self.discharge_limit_delivering_since >= DISCHARGE_LIMIT_GUARD_SECONDS:
            _LOGGER.info(
                "Discharge hold: the battery still delivers %.0f W with 1040 = 0 — also holding the min SOC at %.1f%%",
                battery_power,
                soc,
            )
            self.discharge_limit_guard_soc = soc

    async def _async_clear_limit_guard(self) -> None:
        """End the guard on a 1040 hold and hand 1042 back to the user's limit."""
        self.discharge_limit_delivering_since = None
        if self.discharge_limit_guard_soc is None:
            return
        self.discharge_limit_guard_soc = None
        await self.async_write_min_soc()

    async def async_release_discharge_hold(self) -> None:
        """End a discharge hold: restore 1040 and any guard on it, or hand 1042 back."""
        self.discharge_hold_min_soc = None
        if not self.hold_use_discharge_limit:
            await self.async_write_min_soc()
            return
        try:
            await self.async_restore_discharge_limit()
        finally:
            await self._async_clear_limit_guard()

    def control_settle_seconds(self) -> float:
        """Time the inverter needs without writes to return to internal control."""
        return self.inverter_timeout + CONTROL_SETTLE_MARGIN_SECONDS

    def control_settle_remaining(self) -> float:
        """Seconds left of the settling wait after the last charge or discharge stop."""
        return max(0.0, self.control_settle_seconds() - (time.time() - self.last_stop_time))

    def control_settling(self) -> bool:
        """True while the inverter settles after the last charge or discharge stop.

        Any write to the battery management registers restarts the inverter's
        timeout, so keep-alive writes must wait until this is False.
        """
        return self.control_settle_remaining() > 0.0

    def mark_communication_lost(self, error: str | None) -> None:
        self.communication_ok = False
        self.last_error = error

    def mark_communication_restored(self) -> bool:
        was_disconnected = not self.communication_ok
        self.communication_ok = True
        self.last_error = None
        return was_disconnected

    def set_resume_pending(self, switch_key: str, pending: bool) -> None:
        if pending:
            self.resume_pending_switches.add(switch_key)
            self.control_fault_latched = True
            return

        self.resume_pending_switches.discard(switch_key)
        self.control_fault_latched = bool(self.resume_pending_switches)

    def notify_connection_restored(self) -> None:
        for switch in self.runtime_switches.values():
            handler = getattr(switch, "handle_connection_restored", None)
            if handler is not None:
                handler()


async def _read_optional_at_setup(read, description):
    """Read an identity register, tolerating an inverter that lacks it.

    Setup only reads diagnostics here and every caller already copes with None,
    so a missing register must not stop the integration from loading. A real
    connection problem still raises and lands as ConfigEntryNotReady.
    """
    try:
        return await read()
    except KostalModbusRequestError as err:
        _LOGGER.info("This inverter does not implement %s: %s", description, err)
        return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kostal Modbus Control from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    port = DEFAULT_PORT  # Always 1502 for Plenticore
    unit_id = DEFAULT_UNIT_ID  # Always 71 for Plenticore battery management
    timeout = entry.data.get(CONF_MODBUS_TIMEOUT, DEFAULT_MODBUS_TIMEOUT)

    _LOGGER.info("Setting up Kostal Modbus: host=%s port=%s unit_id=%s", host, port, unit_id)

    handler = KostalModbusHandler(host, port, unit_id)
    try:
        await handler.connect()
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot connect to Kostal inverter at {host}:{port}") from err

    modbus_byte_order = await _read_optional_at_setup(
        partial(handler.read_uint16, REG_MODBUS_BYTE_ORDER), "the byte-order register"
    )
    handler.set_modbus_byte_order(modbus_byte_order)

    # Read static string registers from inverter
    inverter_model = await _read_optional_at_setup(
        partial(handler.read_string, REG_MODEL, 16), "the model register"
    ) or ""
    inverter_power_class = await _read_optional_at_setup(
        partial(handler.read_string, REG_POWER_CLASS, 16), "the power class register"
    ) or ""
    inverter_max_power_w = await _read_optional_at_setup(
        partial(handler.read_uint16, REG_INVERTER_MAX_POWER), "the inverter max power register"
    )
    _LOGGER.info(
        "Inverter model=%r power_class=%r max_power=%s W", inverter_model, inverter_power_class, inverter_max_power_w
    )

    battery_type_raw = await _read_optional_at_setup(
        partial(handler.read_uint16, REG_BATTERY_TYPE), "the battery type register"
    )
    battery_type_name = BATTERY_TYPE_MAP.get(battery_type_raw, f"Unknown (0x{battery_type_raw:04X})") if battery_type_raw is not None else None

    # Register device with static info (string registers are not reliable via Modbus on all firmware)
    device_registry = dr.async_get(hass)
    if inverter_model and inverter_power_class:
        device_name = f"{inverter_model} {inverter_power_class}"
    elif inverter_model:
        device_name = inverter_model
    else:
        device_name = f"Kostal Inverter {host}"
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Kostal",
        model=device_name,
        name=device_name,
        hw_version=battery_type_name,
    )
    
    inverter_type = entry.data.get(CONF_INVERTER_TYPE, "hybrid")
    charge_discharge_reg = REG_BATTERY_AC_POWER_SETPOINT_W if inverter_type == INVERTER_TYPE_BI else REG_BATTERY_DC_POWER_SETPOINT_W
    _LOGGER.info("Inverter type=%r → charge/discharge register=%d", inverter_type, charge_discharge_reg)

    # Set up KSEM handler if configured
    ksem_handler: KostalModbusHandler | None = None
    ksem_host = entry.data.get(CONF_KSEM_HOST, "").strip()
    if ksem_host:
        ksem_handler = KostalModbusHandler(ksem_host, KSEM_PORT, KSEM_SLAVE_ID)
        # KSEM always uses big-endian word order (ABCD) — no word swap
        ksem_handler._word_swapped_32bit = False
        try:
            await ksem_handler.connect()
            _LOGGER.info("Connected to KSEM at %s:%s", ksem_host, KSEM_PORT)
        except Exception as err:
            _LOGGER.warning("Cannot connect to KSEM at %s — energy sensors will be unavailable: %s", ksem_host, err)
            ksem_handler = None

    data = KostalData(
        handler=handler,
        inverter_timeout=timeout,
        inverter_model=inverter_model,
        inverter_power_class=inverter_power_class,
        inverter_max_power_w=float(inverter_max_power_w) if inverter_max_power_w else None,
        charge_discharge_reg=charge_discharge_reg,
        ksem_handler=ksem_handler,
    )

    data.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
    data.load_storage_data(await data.store.async_load())

    coordinator = KostalCoordinator(hass, handler, data, host)
    # Use hass.async_create_background_task for broad HA version compatibility
    hass.async_create_background_task(
        coordinator.async_refresh(),
        "kostal_modbus_initial_refresh",
    )
    data.coordinator = coordinator
    _apply_grid_control_options(entry.options, data)
    _apply_hold_options(entry.options, data)

    hass.data[DOMAIN][entry.entry_id] = data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_update_listener))

    return True


async def _async_options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply changed options.

    The Inverter Control switch and its sensors only exist while a grid entity
    is selected, so adding or removing it needs a reload. Tuning changes are
    applied to the running loop directly.
    """
    data: KostalData = hass.data[DOMAIN][entry.entry_id]
    new_entity = entry.options.get(CONF_SOURCE_GRID_POWER_ENTITY) or None
    if bool(new_entity) != bool(data.source_grid_power_entity):
        await hass.config_entries.async_reload(entry.entry_id)
        return
    _apply_grid_control_options(entry.options, data)
    previous_use_limit = data.hold_use_discharge_limit
    _apply_hold_options(entry.options, data)
    if data.hold_use_discharge_limit != previous_use_limit:
        await _async_switch_hold_register(data, previous_use_limit)


async def _async_switch_hold_register(data: KostalData, used_limit: bool) -> None:
    """Move a running hold to the register the option now selects: the new one first, so the hold has no gap."""
    # The next 1040 hold starts over; 1042 is rewritten below or times out
    data.discharge_limit_delivering_since = None
    data.discharge_limit_guard_soc = None
    if data.control_settling():
        # A write now would keep a stopped setpoint alive; the old register times out by itself
        return
    try:
        hold = data.discharge_hold_min_soc
        if hold is not None:
            await data.async_write_discharge_hold(hold)
        if used_limit:
            await data.async_restore_discharge_limit()
        elif hold is not None:
            await data.async_write_min_soc()
    except Exception as err:
        _LOGGER.warning("Discharge hold: could not move the hold to the selected register: %s", err)


def _apply_hold_options(options: Any, data: KostalData) -> None:
    """Copy the discharge hold options to the runtime data; the holds use them on their next write."""
    data.hold_use_discharge_limit = bool(
        options.get(CONF_HOLD_USE_DISCHARGE_LIMIT, DEFAULT_HOLD_USE_DISCHARGE_LIMIT)
    )
    offset = float(options.get(CONF_HOLD_SOC_OFFSET, DEFAULT_HOLD_SOC_OFFSET))
    data.hold_soc_offset = min(HOLD_SOC_OFFSET_RANGE[1], max(HOLD_SOC_OFFSET_RANGE[0], offset))


def _apply_grid_control_options(options: Any, data: KostalData) -> None:
    """Copy the grid control settings from the options to the runtime data."""
    new_entity = options.get(CONF_SOURCE_GRID_POWER_ENTITY) or None
    if new_entity != data.source_grid_power_entity:
        # A different source makes the old filtered value meaningless
        data.last_inverter_control_filtered_load_w = None
    data.source_grid_power_entity = new_entity
    data.grid_target_w = float(options.get(CONF_GRID_TARGET_W, DEFAULT_GRID_TARGET_W))
    data.grid_deadband_w = float(options.get(CONF_GRID_DEADBAND_W, DEFAULT_GRID_DEADBAND_W))
    max_discharge = options.get(CONF_EXTERNAL_CONTROL_MAX_DISCHARGE_W)
    max_charge = options.get(CONF_EXTERNAL_CONTROL_MAX_CHARGE_W)
    data.external_control_max_discharge_w = None if max_discharge is None else float(max_discharge)
    data.external_control_max_charge_w = None if max_charge is None else float(max_charge)
    data.external_control_hysteresis_w = float(
        options.get(CONF_EXTERNAL_CONTROL_HYSTERESIS_W, DEFAULT_EXTERNAL_CONTROL_HYSTERESIS_W)
    )
    ema_alpha = float(options.get(CONF_EXTERNAL_CONTROL_EMA_ALPHA, DEFAULT_EXTERNAL_CONTROL_EMA_ALPHA))
    # Alpha 0 would freeze the filter on its first reading
    data.external_control_ema_alpha = min(1.0, max(MIN_EXTERNAL_CONTROL_EMA_ALPHA, ema_alpha))


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data: KostalData = hass.data[DOMAIN].pop(entry.entry_id)
        await data.handler.close()
        if data.ksem_handler is not None:
            await data.ksem_handler.close()

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the learned battery values of a deleted config entry."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
